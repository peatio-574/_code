"""考试：组卷、发布/撤回、学员参加、自动保存、交卷计分、模拟考试、成绩统计。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, actor_primary_campus, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import conflict, forbidden, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin")

QUESTION_TYPES = ["single", "multiple", "true_false", "fill", "qa", "group"]


class SectionInput(BaseModel):
    type: str
    description: str
    question_ids: list[int]


class ExamInput(BaseModel):
    id: int | None = None
    title: str = ""
    exam_time: int = 0
    end_time: int = 0
    duration: int = 0
    pass_score: int = 60
    total_score: int | None = None
    sections: list[SectionInput] = []
    status: int = 1


class StatusInput(BaseModel):
    id: int
    status: int


class AttemptQuery(BaseModel):
    pass


class AnswerItem(BaseModel):
    question_id: int
    answer: str = ""


class SubmitInput(BaseModel):
    attempt_id: int
    answers: list[AnswerItem] = []


def _normalize_choices(value: str) -> str:
    return "".join(sorted(ch for ch in value.upper() if ch.isalpha()))


def _normalize_simple(value: str) -> str:
    return value.strip().rstrip(".").lower()


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).lower()


def _is_correct(question_type: str, expected: str, submitted: str) -> bool:
    if question_type == "multiple":
        return _normalize_choices(expected) == _normalize_choices(submitted)
    if question_type in ("single", "true_false"):
        return _normalize_simple(expected) == _normalize_simple(submitted)
    return _normalize_text(expected) == _normalize_text(submitted)


def _exam_display_status(row) -> str:
    timestamp = now()
    if row["status"] == 0:
        return "draft"
    if row["status"] == 2:
        return "withdrawn"
    if timestamp < row["exam_time"]:
        return "not_started"
    if row["end_time"] and timestamp > row["end_time"]:
        return "ended"
    return "in_progress"


@admin_router.get("/exams")
def list_exams(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    where = ["e.is_mock=0"]
    params: dict = {}
    if keyword:
        where.append("e.title LIKE :kw")
        params["kw"] = f"%{keyword}%"
    clause = " AND ".join(where)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM exams e WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT e.id, e.title, e.exam_time, e.duration, e.status, e.pass_score, "
                "e.created_by, e.published_at, e.created_at, e.updated_at, "
                "(e.exam_time + e.duration*60) end_time, "
                "COALESCE(NULLIF(creator.display_name,''), creator.username) creator_name, "
                "COUNT(DISTINCT esq.question_id) total_questions, "
                "COUNT(DISTINCT a.id) attempt_count, "
                "SUM(CASE WHEN a.status=1 AND a.total_score>=e.pass_score THEN 1 ELSE 0 END) pass_count, "
                "CAST(COALESCE(AVG(CASE WHEN a.status=1 THEN a.total_score END),0) AS DOUBLE) average_score "
                "FROM exams e JOIN users creator ON creator.id=e.created_by "
                "LEFT JOIN exam_sections es ON es.exam_id=e.id "
                "LEFT JOIN exam_section_questions esq ON esq.exam_section_id=es.id "
                "LEFT JOIN exam_attempts a ON a.exam_id=e.id "
                f"WHERE {clause} GROUP BY e.id, creator.display_name, creator.username "
                "ORDER BY e.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["total_questions"] = int(item["total_questions"] or 0)
        item["attempt_count"] = int(item["attempt_count"] or 0)
        item["pass_count"] = int(item["pass_count"] or 0)
        item["average_score"] = float(item["average_score"] or 0)
        item["display_status"] = _exam_display_status(row)
        items.append(item)
    return ok(page_result(items, total, page, size))


def _exam_value(connection, exam_id: int) -> dict:
    exam = connection.execute(
        text(
            "SELECT id, title, code, exam_time, duration, status, pass_score, created_by, "
            "published_at, created_at, updated_at, (exam_time + duration*60) end_time "
            "FROM exams WHERE id=:id AND is_mock=0"
        ),
        {"id": exam_id},
    ).mappings().first()
    if exam is None:
        raise not_found("试卷不存在")
    sections = []
    for section in connection.execute(
        text(
            "SELECT id, type, description, sort_order FROM exam_sections "
            "WHERE exam_id=:id ORDER BY sort_order"
        ),
        {"id": exam_id},
    ).mappings().all():
        questions = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.status, q.score "
                "FROM exam_section_questions esq JOIN questions q ON q.id=esq.question_id "
                "WHERE esq.exam_section_id=:sid ORDER BY esq.sort_order"
            ),
            {"sid": section["id"]},
        ).mappings().all()
        sections.append({**dict(section), "questions": [dict(q) for q in questions]})
    return {"exam": dict(exam), "sections": sections}


@admin_router.post("/exam")
def create_exam(payload: ExamInput, request: Request):
    title = payload.title.strip()
    if not title or payload.exam_time <= 0 or payload.duration <= 0 or payload.pass_score < 0 or not payload.sections:
        raise validation("试卷数据不完整")
    with named_lock("exams:code") as connection:
        actor = actor_id(request)
        timestamp = now()
        import uuid

        code = f"EXAM-{uuid.uuid4()}"
        exam_id = connection.execute(
            text(
                "INSERT INTO exams(title, code, exam_time, duration, pass_score, status, is_mock, "
                "created_by, published_at, created_at, updated_at) VALUES(:title, :code, "
                ":exam_time, :duration, :pass_score, :status, 0, :created_by, :published_at, "
                ":created_at, :updated_at)"
            ),
            {
                "title": title,
                "code": code,
                "exam_time": payload.exam_time,
                "duration": payload.duration,
                "pass_score": payload.pass_score,
                "status": 1 if payload.status else 0,
                "created_by": actor,
                "published_at": timestamp if payload.status else 0,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ).lastrowid
        _insert_sections(connection, exam_id, payload.sections)
        value = _exam_value(connection, exam_id)
    return ok(value)


def _insert_sections(connection, exam_id: int, sections: list[SectionInput]) -> None:
    for index, section in enumerate(sections, start=1):
        if section.type not in QUESTION_TYPES or not section.description.strip() or not section.question_ids:
            raise validation("试卷分组不合法")
        section_id = connection.execute(
            text(
                "INSERT INTO exam_sections(exam_id, type, description, sort_order) "
                "VALUES(:exam_id, :type, :description, :sort_order)"
            ),
            {
                "exam_id": exam_id,
                "type": section.type,
                "description": section.description.strip(),
                "sort_order": index,
            },
        ).lastrowid
        seen: set[int] = set()
        order = 0
        for question_id in section.question_ids:
            if question_id <= 0 or question_id in seen:
                continue
            seen.add(question_id)
            kind = connection.execute(
                text("SELECT type FROM questions WHERE id=:id"), {"id": question_id}
            ).scalar()
            if kind != section.type:
                raise validation("题目与分组题型不一致")
            order += 1
            connection.execute(
                text(
                    "INSERT INTO exam_section_questions(exam_section_id, question_id, sort_order) "
                    "VALUES(:sid, :qid, :order)"
                ),
                {"sid": section_id, "qid": question_id, "order": order},
            )
        if order == 0:
            raise validation("分组至少需要一道题")


@admin_router.get("/exam/{exam_id}")
def get_exam(exam_id: int):
    with get_engine().connect() as connection:
        value = _exam_value(connection, exam_id)
        connection.commit()
    return ok(value)


@admin_router.put("/exam/{exam_id}")
def update_exam(exam_id: int, payload: ExamInput, request: Request):
    with named_lock(f"exam:update:{exam_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM exams WHERE id=:id AND is_mock=0"), {"id": exam_id}
        ).scalar()
        if not exists:
            raise not_found("试卷不存在")
        attempts = connection.execute(
            text("SELECT COUNT(*) FROM exam_attempts WHERE exam_id=:id"), {"id": exam_id}
        ).scalar()
        if attempts:
            raise conflict("已有考试记录的试卷不可修改")
        fields = ["exam_time=:exam_time", "duration=:duration", "pass_score=:pass_score", "updated_at=:ts"]
        params: dict = {
            "exam_time": payload.exam_time,
            "duration": payload.duration,
            "pass_score": payload.pass_score,
            "ts": now(),
            "id": exam_id,
        }
        if payload.title.strip():
            fields.append("title=:title")
            params["title"] = payload.title.strip()
        if payload.status in (0, 1, 2):
            fields.append("status=:status")
            params["status"] = payload.status
        connection.execute(text(f"UPDATE exams SET {', '.join(fields)} WHERE id=:id"), params)
        if payload.sections:
            connection.execute(
                text(
                    "DELETE FROM exam_section_questions WHERE exam_section_id IN "
                    "(SELECT id FROM exam_sections WHERE exam_id=:id)"
                ),
                {"id": exam_id},
            )
            connection.execute(text("DELETE FROM exam_sections WHERE exam_id=:id"), {"id": exam_id})
            _insert_sections(connection, exam_id, payload.sections)
        value = _exam_value(connection, exam_id)
    return ok(value)


@admin_router.delete("/exam/{exam_id}")
def delete_exam(exam_id: int):
    with named_lock(f"exam:delete:{exam_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM exams WHERE id=:id"), {"id": exam_id}
        ).scalar()
        if not exists:
            raise not_found("试卷不存在")
        _delete_exam(connection, exam_id)
    return ok({"id": exam_id})


def _delete_exam(connection, exam_id: int) -> None:
    connection.execute(
        text(
            "DELETE FROM exam_answers WHERE attempt_id IN "
            "(SELECT id FROM exam_attempts WHERE exam_id=:id)"
        ),
        {"id": exam_id},
    )
    connection.execute(
        text(
            "DELETE FROM exam_section_questions WHERE exam_section_id IN "
            "(SELECT id FROM exam_sections WHERE exam_id=:id)"
        ),
        {"id": exam_id},
    )
    connection.execute(text("DELETE FROM exam_attempts WHERE exam_id=:id"), {"id": exam_id})
    connection.execute(text("DELETE FROM exam_sections WHERE exam_id=:id"), {"id": exam_id})
    connection.execute(text("DELETE FROM exams WHERE id=:id"), {"id": exam_id})


@admin_router.post("/exams/batch-delete")
def batch_delete(payload: dict):
    ids = payload.get("ids") or []
    if not ids:
        raise validation("请选择要删除的试卷")
    with get_engine().begin() as connection:
        for exam_id in ids:
            _delete_exam(connection, exam_id)
    return ok({"deleted_count": len(ids)})


@admin_router.post("/exam/{exam_id}/publish")
def publish_exam(exam_id: int, request: Request):
    with get_engine().begin() as connection:
        questions = connection.execute(
            text(
                "SELECT COUNT(*) FROM exam_section_questions esq JOIN exam_sections es "
                "ON es.id=esq.exam_section_id WHERE es.exam_id=:id"
            ),
            {"id": exam_id},
        ).scalar()
        if not questions:
            raise validation("试卷没有题目，无法发布")
        result = connection.execute(
            text(
                "UPDATE exams SET status=1, published_at=:ts, updated_at=:ts WHERE id=:id"
            ),
            {"ts": now(), "id": exam_id},
        )
        if result.rowcount == 0:
            raise not_found("试卷不存在")
    return ok({"id": exam_id, "status": 1})


@admin_router.post("/exam/{exam_id}/withdraw")
def withdraw_exam(exam_id: int):
    with get_engine().begin() as connection:
        result = connection.execute(
            text("UPDATE exams SET status=2, updated_at=:ts WHERE id=:id"),
            {"ts": now(), "id": exam_id},
        )
        if result.rowcount == 0:
            raise not_found("试卷不存在")
    return ok({"id": exam_id, "status": 2})


@admin_router.get("/exam-attempts")
def list_attempts(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    where = ["1=1"]
    params: dict = {}
    if keyword:
        where.append("(u.username LIKE :kw OR u.display_name LIKE :kw OR e.title LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    clause = " AND ".join(where)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(
                "SELECT COUNT(*) FROM exam_attempts a JOIN users u ON u.id=a.user_id "
                f"JOIN exams e ON e.id=a.exam_id WHERE {clause}"
            ),
            params,
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT a.id, a.user_id, u.username, u.display_name, a.exam_id, e.title exam_title, "
                "a.status, a.start_time, a.submitted_at, a.total_score "
                "FROM exam_attempts a JOIN users u ON u.id=a.user_id JOIN exams e ON e.id=a.exam_id "
                f"WHERE {clause} ORDER BY a.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([dict(r) for r in rows], total, page, size))


# ==================== 学员端考试 ====================


@router.get("/exams/statistics")
def statistics(request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        row = connection.execute(
            text(
                "SELECT COUNT(*) attempt_count, "
                "CAST(COALESCE(SUM(CASE WHEN a.status=1 AND a.total_score>=e.pass_score THEN 1 ELSE 0 END),0) AS SIGNED) pass_count, "
                "CAST(COALESCE(AVG(CASE WHEN a.status=1 THEN a.total_score END),0) AS DOUBLE) average_score "
                "FROM exam_attempts a JOIN exams e ON e.id=a.exam_id "
                "WHERE a.user_id=:uid AND e.is_mock=0"
            ),
            {"uid": user_id},
        ).mappings().first()
        connection.commit()
    return ok(dict(row))


@router.get("/exams/history")
def history(request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        rows = connection.execute(
            text(
                "SELECT a.id attempt_id, a.exam_id, e.title, a.status, a.start_time, a.submitted_at, "
                "a.total_score, e.pass_score FROM exam_attempts a JOIN exams e ON e.id=a.exam_id "
                "WHERE a.user_id=:uid AND e.is_mock=0 ORDER BY a.id DESC LIMIT 100"
            ),
            {"uid": user_id},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["passed"] = row["status"] == 1 and row["total_score"] >= row["pass_score"]
        items.append(item)
    return ok({"items": items})


@router.get("/exams/available")
def available(request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        rows = connection.execute(
            text(
                "SELECT e.id exam_id, e.title, e.exam_time, e.duration, e.pass_score, "
                "(SELECT COUNT(*) FROM exam_section_questions esq JOIN exam_sections es "
                " ON es.id=esq.exam_section_id WHERE es.exam_id=e.id) total_questions, "
                "COALESCE((SELECT a.id FROM exam_attempts a WHERE a.exam_id=e.id AND a.user_id=:uid "
                "AND a.status=0 ORDER BY a.id DESC LIMIT 1),0) attempt_id "
                "FROM exams e WHERE e.is_mock=0 AND e.status=1 "
                "AND (e.created_by=(SELECT manager_id FROM users WHERE id=:uid) OR EXISTS ("
                "SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=e.created_by "
                "AND r.code='system_admin' AND r.status=1)) ORDER BY e.exam_time DESC, e.id DESC"
            ),
            {"uid": user_id},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["attempt_id"] = item["attempt_id"] or None
        items.append(item)
    return ok({"items": items})


@router.post("/exams/{exam_id}/attempt")
def start_attempt(exam_id: int, request: Request):
    with named_lock(f"exam_attempt:{actor_id(request)}:{exam_id}") as connection:
        user_id = actor_id(request)
        exam = connection.execute(
            text(
                "SELECT id, title, exam_time, duration, status, pass_score FROM exams "
                "WHERE id=:id AND is_mock=0"
            ),
            {"id": exam_id},
        ).mappings().first()
        if exam is None:
            raise not_found("试卷不存在")
        if exam["status"] != 1:
            raise not_found("试卷未发布")
        eligible = connection.execute(
            text(
                "SELECT COUNT(*) FROM exams e WHERE e.id=:id AND "
                "(e.created_by=(SELECT manager_id FROM users WHERE id=:uid) OR EXISTS ("
                "SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                "WHERE ur.user_id=e.created_by AND r.code='system_admin' AND r.status=1))"
            ),
            {"id": exam_id, "uid": user_id},
        ).scalar()
        if not eligible:
            raise forbidden()
        timestamp = now()
        if timestamp < exam["exam_time"]:
            raise validation("考试尚未开始")
        existing = connection.execute(
            text(
                "SELECT id FROM exam_attempts WHERE user_id=:uid AND exam_id=:eid AND status=0 "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"uid": user_id, "eid": exam_id},
        ).scalar()
        if existing is None:
            campus_id = actor_primary_campus(connection, user_id)
            existing = connection.execute(
                text(
                    "INSERT INTO exam_attempts(user_id, exam_id, start_time, end_time, status, "
                    "campus_id, created_at, updated_at) VALUES(:uid, :eid, :start, :end, 0, "
                    ":campus_id, :ts, :ts)"
                ),
                {
                    "uid": user_id,
                    "eid": exam_id,
                    "start": timestamp,
                    "end": timestamp + exam["duration"] * 60,
                    "campus_id": campus_id,
                    "ts": timestamp,
                },
            ).lastrowid
        attempt = connection.execute(
            text(
                "SELECT id, user_id, exam_id, start_time, end_time, status FROM exam_attempts "
                "WHERE id=:id"
            ),
            {"id": existing},
        ).mappings().first()
        response = _attempt_response(connection, attempt, exam["title"], exam["duration"])
    return ok(response)


def _attempt_response(connection, attempt, title: str, duration: int) -> dict:
    top_ids = connection.execute(
        text(
            "SELECT esq.question_id FROM exam_section_questions esq JOIN exam_sections es "
            "ON es.id=esq.exam_section_id WHERE es.exam_id=:eid ORDER BY es.sort_order, esq.sort_order"
        ),
        {"eid": attempt["exam_id"]},
    ).fetchall()
    questions = []
    for (question_id,) in top_ids:
        question = connection.execute(
            text(
                "SELECT id, type, title, options, status, score FROM questions WHERE id=:id"
            ),
            {"id": question_id},
        ).mappings().first()
        if question is None:
            continue
        item = dict(question)
        if question["type"] == "group":
            item["children"] = [
                dict(c)
                for c in connection.execute(
                    text(
                        "SELECT id, type, title, options, status, score FROM questions "
                        "WHERE parent_id=:id AND status=1 ORDER BY sort_order, id"
                    ),
                    {"id": question_id},
                ).mappings().all()
            ]
        questions.append(item)
    end_time = attempt["start_time"] + duration * 60
    return {
        "attempt_id": attempt["id"],
        "exam_id": attempt["exam_id"],
        "title": title,
        "start_time": attempt["start_time"],
        "end_time": end_time,
        "duration": duration,
        "submitted": attempt["status"] == 1,
        "remaining_seconds": max(end_time - now(), 0),
        "questions": questions,
    }


@router.get("/exams/attempt")
def get_attempt(request: Request):
    attempt_id = request.query_params.get("attempt_id")
    if not attempt_id or not attempt_id.isdigit():
        raise validation("invalid attempt id")
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        attempt = connection.execute(
            text(
                "SELECT id, user_id, exam_id, start_time, end_time, status FROM exam_attempts "
                "WHERE id=:id"
            ),
            {"id": int(attempt_id)},
        ).mappings().first()
        if attempt is None:
            raise not_found("考试记录不存在")
        if attempt["user_id"] != user_id:
            raise forbidden()
        exam = connection.execute(
            text("SELECT title, duration FROM exams WHERE id=:id"), {"id": attempt["exam_id"]}
        ).mappings().first()
        connection.commit()
    return ok(_attempt_response(connection, attempt, exam["title"], exam["duration"]))


def _persist_answers(connection, attempt, answers: list[AnswerItem], ended: bool) -> tuple[int, bool]:
    timestamp = now()
    for answer in answers:
        if answer.question_id <= 0:
            continue
        question = connection.execute(
            text(
                "SELECT q.id, q.type, q.answer, q.score FROM questions q WHERE q.id=:qid AND EXISTS ("
                "SELECT 1 FROM exam_section_questions esq JOIN exam_sections es ON es.id=esq.exam_section_id "
                "WHERE es.exam_id=:eid AND (esq.question_id=q.id OR esq.question_id=q.parent_id))"
            ),
            {"qid": answer.question_id, "eid": attempt["exam_id"]},
        ).mappings().first()
        if question is None:
            continue
        correct = _is_correct(question["type"], question["answer"], answer.answer)
        existing = connection.execute(
            text(
                "SELECT id FROM exam_answers WHERE attempt_id=:aid AND question_id=:qid"
            ),
            {"aid": attempt["id"], "qid": question["id"]},
        ).scalar()
        if existing:
            connection.execute(
                text(
                    "UPDATE exam_answers SET answer=:answer, is_correct=:correct, score=:score, "
                    "updated_at=:ts WHERE id=:id"
                ),
                {
                    "answer": answer.answer,
                    "correct": 1 if correct else 0,
                    "score": question["score"] if correct else 0,
                    "ts": timestamp,
                    "id": existing,
                },
            )
        else:
            connection.execute(
                text(
                    "INSERT INTO exam_answers(attempt_id, question_id, answer, is_correct, score, "
                    "updated_at) VALUES(:aid, :qid, :answer, :correct, :score, :ts)"
                ),
                {
                    "aid": attempt["id"],
                    "qid": question["id"],
                    "answer": answer.answer,
                    "correct": 1 if correct else 0,
                    "score": question["score"] if correct else 0,
                    "ts": timestamp,
                },
            )
    total_score = connection.execute(
        text(
            "SELECT CAST(COALESCE(SUM(score),0) AS SIGNED) FROM exam_answers WHERE attempt_id=:aid"
        ),
        {"aid": attempt["id"]},
    ).scalar()
    if ended:
        connection.execute(
            text(
                "UPDATE exam_attempts SET status=1, submitted_at=:ts, total_score=:score, "
                "updated_at=:ts WHERE id=:id"
            ),
            {"ts": timestamp, "score": total_score, "id": attempt["id"]},
        )
    return total_score, ended


@router.post("/exams/answers")
def save_answers(payload: SubmitInput, request: Request):
    with named_lock(f"exam_save:{payload.attempt_id}") as connection:
        user_id = actor_id(request)
        attempt = connection.execute(
            text(
                "SELECT id, user_id, exam_id, start_time, end_time, status FROM exam_attempts "
                "WHERE id=:id"
            ),
            {"id": payload.attempt_id},
        ).mappings().first()
        if attempt is None:
            raise not_found("考试记录不存在")
        if attempt["user_id"] != user_id:
            raise forbidden()
        if attempt["status"] == 1:
            total = connection.execute(
                text("SELECT total_score FROM exam_attempts WHERE id=:id"), {"id": attempt["id"]}
            ).scalar()
            return ok(
                {
                    "saved": True,
                    "ended": True,
                    "submitted": True,
                    "remaining_seconds": 0,
                    "total_score": total,
                }
            )
        timestamp = now()
        ended = timestamp >= attempt["end_time"]
        total_score, _ = _persist_answers(connection, attempt, payload.answers, ended)
    return ok(
        {
            "saved": True,
            "ended": ended,
            "submitted": ended,
            "remaining_seconds": max(attempt["end_time"] - timestamp, 0),
            "total_score": total_score,
        }
    )


@router.post("/exams/submit")
def submit(payload: SubmitInput, request: Request):
    with named_lock(f"exam_save:{payload.attempt_id}") as connection:
        user_id = actor_id(request)
        attempt = connection.execute(
            text(
                "SELECT id, user_id, exam_id, start_time, end_time, status FROM exam_attempts "
                "WHERE id=:id"
            ),
            {"id": payload.attempt_id},
        ).mappings().first()
        if attempt is None:
            raise not_found("考试记录不存在")
        if attempt["user_id"] != user_id:
            raise forbidden()
        total_score, _ = _persist_answers(connection, attempt, payload.answers, True)
    return ok(
        {
            "saved": True,
            "ended": True,
            "submitted": True,
            "remaining_seconds": 0,
            "total_score": total_score,
        }
    )


@router.get("/exams/result")
def result(request: Request):
    attempt_id = request.query_params.get("attempt_id")
    if not attempt_id or not attempt_id.isdigit():
        raise validation("invalid attempt id")
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        summary = connection.execute(
            text(
                "SELECT a.user_id, a.exam_id, e.title, a.status, a.submitted_at, a.total_score, "
                "e.pass_score FROM exam_attempts a JOIN exams e ON e.id=a.exam_id WHERE a.id=:id"
            ),
            {"id": int(attempt_id)},
        ).mappings().first()
        if summary is None:
            raise not_found("考试记录不存在")
        if summary["user_id"] != user_id:
            raise forbidden()
        if summary["status"] != 1:
            raise validation("考试结果尚未生成")
        question_ids = connection.execute(
            text(
                "SELECT esq.question_id FROM exam_section_questions esq JOIN exam_sections es "
                "ON es.id=esq.exam_section_id WHERE es.exam_id=:eid ORDER BY es.sort_order, esq.sort_order"
            ),
            {"eid": summary["exam_id"]},
        ).fetchall()
        questions = []
        for (question_id,) in question_ids:
            row = connection.execute(
                text(
                    "SELECT q.id, q.type, q.title, q.options, q.status, q.score, q.answer correct_answer, "
                    "ea.answer user_answer, ea.is_correct, ea.score earned_score "
                    "FROM questions q LEFT JOIN exam_answers ea ON ea.question_id=q.id AND ea.attempt_id=:aid "
                    "WHERE q.id=:qid"
                ),
                {"aid": int(attempt_id), "qid": question_id},
            ).mappings().first()
            if row is None:
                continue
            item = dict(row)
            item["user_answer"] = item["user_answer"] or ""
            item["answered"] = item["user_answer"] != ""
            item["is_correct"] = bool(item["is_correct"])
            item["earned_score"] = item["earned_score"] or 0
            questions.append(item)
        connection.commit()
    return ok(
        {
            "attempt_id": int(attempt_id),
            "exam_id": summary["exam_id"],
            "title": summary["title"],
            "submitted_at": summary["submitted_at"],
            "total_score": summary["total_score"],
            "pass_score": summary["pass_score"],
            "passed": summary["total_score"] >= summary["pass_score"],
            "questions": questions,
        }
    )


# ==================== 模拟考试 ====================


def _mock_config(connection) -> dict:
    rows = connection.execute(
        text(
            "SELECT `key`, value FROM sys_config WHERE `key` IN ('auto_exam_enabled','auto_exam_title',"
            "'auto_exam_total','auto_exam_duration','auto_exam_categories','auto_exam_ratios',"
            "'auto_exam_include_group','mock_exam_total','mock_exam_duration','mock_exam_ratios')"
        )
    ).fetchall()
    stored = {row[0]: row[1] for row in rows}

    def get(key: str):
        return stored.get(key)

    enabled = str(get("auto_exam_enabled") or "true").lower() not in ("0", "false")
    title = (get("auto_exam_title") or "模拟考试").strip()
    use_auto = get("auto_exam_total") is not None or get("auto_exam_ratios") is not None
    import json

    ratios_raw = get("auto_exam_ratios") if use_auto else get("mock_exam_ratios")
    try:
        ratios = json.loads(ratios_raw) if ratios_raw else {"single": 40, "multiple": 20, "true_false": 20, "fill": 10, "qa": 10}
    except Exception:
        ratios = {"single": 40, "multiple": 20, "true_false": 20, "fill": 10, "qa": 10}
    try:
        import json as _json

        categories = _json.loads(get("auto_exam_categories") or "[]")
    except Exception:
        categories = []

    def to_int(value, fallback):
        try:
            return int(value)
        except Exception:
            return fallback

    total = to_int(get("auto_exam_total") if use_auto else get("mock_exam_total"), 20)
    duration = to_int(get("auto_exam_duration") if use_auto else get("mock_exam_duration"), 30)
    include_group = str(get("auto_exam_include_group") or "false").lower() not in ("0", "false")
    return {
        "enabled": enabled,
        "title": title,
        "total": max(1, min(total, 500)),
        "duration": max(1, min(duration, 600)),
        "ratios": ratios,
        "categories": categories,
        "include_group": include_group,
    }


@router.post("/exams/mock")
def mock_exam(request: Request):
    with named_lock(f"exam_mock:{actor_id(request)}") as connection:
        user_id = actor_id(request)
        config = _mock_config(connection)
        if not config["enabled"]:
            raise not_found("模拟考试未开启")
        types = ["single", "multiple", "true_false", "fill", "qa"]
        if config["include_group"]:
            types.append("group")
        ratio_sum = sum(int(config["ratios"].get(t, 0) or 0) for t in types)
        if ratio_sum <= 0:
            raise not_found("模拟考试未配置题目比例")
        counts = []
        allocated = 0
        total = config["total"]
        for question_type in types:
            count = (total * int(config["ratios"].get(question_type, 0) or 0) + ratio_sum // 2) // ratio_sum
            counts.append(count)
            allocated += count
        counts[0] = max(counts[0] + total - allocated, 0)
        selected = []
        for question_type, count in zip(types, counts):
            if count <= 0:
                continue
            params: dict = {"type": question_type}
            where = "type=:type AND status=1 AND parent_id=0"
            if config["categories"]:
                placeholders = ",".join(f":cat{i}" for i in range(len(config["categories"])))
                where += f" AND category_id IN ({placeholders})"
                for index, value in enumerate(config["categories"]):
                    params[f"cat{index}"] = int(value)
            ids = [
                row[0]
                for row in connection.execute(
                    text(f"SELECT id FROM questions WHERE {where} ORDER BY RAND() LIMIT :count"),
                    {**params, "count": count},
                ).fetchall()
            ]
            if ids:
                selected.append((question_type, ids))
        if not selected:
            raise not_found("题库暂无可用于模拟考试的题目")
        timestamp = now()
        exam_id = connection.execute(
            text(
                "INSERT INTO exams(title, code, exam_time, duration, pass_score, status, is_mock, "
                "created_by, published_at, created_at, updated_at) VALUES(:title, :code, "
                ":exam_time, :duration, 60, 1, 1, :created_by, :exam_time, :ts, :ts)"
            ),
            {
                "title": config["title"],
                "code": f"MOCK-{timestamp}-{user_id}",
                "exam_time": timestamp,
                "duration": config["duration"],
                "created_by": user_id,
                "ts": timestamp,
            },
        ).lastrowid
        for index, (question_type, ids) in enumerate(selected, start=1):
            section_id = connection.execute(
                text(
                    "INSERT INTO exam_sections(exam_id, type, description, sort_order) "
                    "VALUES(:eid, :type, :description, :sort_order)"
                ),
                {"eid": exam_id, "type": question_type, "description": question_type, "sort_order": index},
            ).lastrowid
            for order, question_id in enumerate(ids, start=1):
                connection.execute(
                    text(
                        "INSERT INTO exam_section_questions(exam_section_id, question_id, sort_order) "
                        "VALUES(:sid, :qid, :order)"
                    ),
                    {"sid": section_id, "qid": question_id, "order": order},
                )
        attempt_id = connection.execute(
            text(
                "INSERT INTO exam_attempts(user_id, exam_id, start_time, end_time, status, campus_id, "
                "created_at, updated_at) VALUES(:uid, :eid, :start, :end, 0, :campus_id, :ts, :ts)"
            ),
            {
                "uid": user_id,
                "eid": exam_id,
                "start": timestamp,
                "end": timestamp + config["duration"] * 60,
                "campus_id": campus_id,
                "ts": timestamp,
            },
        ).lastrowid
        attempt = connection.execute(
            text(
                "SELECT id, user_id, exam_id, start_time, end_time, status FROM exam_attempts WHERE id=:id"
            ),
            {"id": attempt_id},
        ).mappings().first()
        response = _attempt_response(connection, attempt, config["title"], config["duration"])
    return ok(response)
