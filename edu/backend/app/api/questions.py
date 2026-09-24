"""题库：练习类型与题目 CRUD、学员取题作答、统计、错题与错题重练。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import conflict, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin")

QUESTION_TYPES = {"single", "multiple", "true_false", "fill", "qa", "group"}


class QuestionInput(BaseModel):
    id: int | None = None
    type: str
    title: str
    options: str = ""
    answer: str = ""
    explanation: str = ""
    status: int = 1
    category_id: int = 0
    score: int = 1
    children: list[dict] = []


class StatusInput(BaseModel):
    id: int
    status: int


class CategoryInput(BaseModel):
    id: int | None = None
    name: str
    parent_id: int = 0
    sort_order: int = 0
    status: int = 1


class AnswerInput(BaseModel):
    question_id: int
    answer: str
    category_id: int | None = None


class RetryAnswerInput(BaseModel):
    attempt_id: int
    question_id: int
    answer: str


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


def _validate_type(value: str) -> None:
    if value not in QUESTION_TYPES:
        raise validation("题型不合法")


@router.get("/question-categories")
def public_categories(request: Request):
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, name, sort_order FROM question_categories "
                "WHERE status=1 ORDER BY sort_order, id"
            )
        ).mappings().all()
        connection.commit()
    return ok({"items": [dict(r) for r in rows]})


def _stats(connection, user_id: int) -> dict:
    row = connection.execute(
        text(
            "SELECT COUNT(*) answered_count, "
            "CAST(COALESCE(SUM(CASE WHEN is_correct=1 THEN 1 ELSE 0 END),0) AS SIGNED) correct_count, "
            "CAST(COALESCE(SUM(CASE WHEN is_correct=0 THEN 1 ELSE 0 END),0) AS SIGNED) wrong_count "
            "FROM question_first_answers WHERE user_id=:uid"
        ),
        {"uid": user_id},
    ).mappings().first()
    total = connection.execute(
        text("SELECT COUNT(*) FROM questions WHERE status=1 AND (parent_id>0 OR type<>'group')")
    ).scalar()
    answered = row["answered_count"]
    correct = row["correct_count"]
    accuracy = (correct / answered * 100) if answered else 0
    progress = (answered / total * 100) if total else 0
    return {
        "answered_count": answered,
        "correct_count": correct,
        "wrong_count": row["wrong_count"],
        "accuracy": accuracy,
        "progress_count": answered,
        "total_count": total,
        "progress": progress,
    }


@router.get("/questions/statistics")
def statistics(request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        result = _stats(connection, user_id)
        connection.commit()
    return ok(result)


@router.get("/questions/random")
def random_question(request: Request):
    question_type = (request.query_params.get("type") or "").strip()
    _validate_type(question_type)
    categories = [int(c) for c in request.query_params.getlist("category_id") if c.isdigit()]
    category = categories[0] if categories else None
    with named_lock(f"practice:{actor_id(request)}") as connection:
        user_id = actor_id(request)
        params: dict = {"uid": user_id, "type": question_type}
        where = ["q.type=:type", "q.status=1", "q.parent_id=0"]
        if categories:
            placeholders = ",".join(f":cat{i}" for i in range(len(categories)))
            where.append(f"q.category_id IN ({placeholders})")
            for index, value in enumerate(categories):
                params[f"cat{index}"] = value
        clause = " AND ".join(where)
        question = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.score, q.category_id, "
                "(SELECT COUNT(*) FROM questions c WHERE c.parent_id=q.id AND c.status=1) child_count "
                "FROM questions q LEFT JOIN question_records qr ON qr.question_id=q.id AND qr.user_id=:uid "
                f"WHERE {clause} AND (qr.id IS NULL OR qr.answered=0) "
                "ORDER BY CASE WHEN qr.id IS NOT NULL THEN 0 ELSE 1 END, RAND() LIMIT 1"
            ),
            params,
        ).mappings().first()
        if question is not None:
            existing = connection.execute(
                text(
                    "SELECT id FROM question_records WHERE user_id=:uid AND question_id=:qid"
                ),
                {"uid": user_id, "qid": question["id"]},
            ).scalar()
            if existing is None:
                connection.execute(
                    text(
                        "INSERT INTO question_records(user_id, question_id, created_at, updated_at) "
                        "VALUES(:uid, :qid, :ts, :ts)"
                    ),
                    {"uid": user_id, "qid": question["id"], "ts": now()},
                )
        children = []
        if question is not None and question["type"] == "group":
            children = [
                dict(r)
                for r in connection.execute(
                    text(
                        "SELECT id, type, title, options, score, category_id FROM questions "
                        "WHERE parent_id=:pid AND status=1 ORDER BY sort_order, id"
                    ),
                    {"pid": question["id"]},
                ).mappings().all()
            ]
        stats = _stats(connection, user_id)
    return ok(
        {
            "question": dict(question) if question else None,
            "children": children,
            "remaining_count": 0,
            "answered_count": stats["answered_count"],
            "correct_count": stats["correct_count"],
            "wrong_count": stats["wrong_count"],
            "no_more_questions": question is None,
        }
    )


@router.post("/questions/answer")
def submit_answer(payload: AnswerInput, request: Request):
    if payload.question_id <= 0 or not payload.answer.strip():
        raise validation("请作答后再提交")
    with get_engine().begin() as connection:
        user_id = actor_id(request)
        question = connection.execute(
            text(
                "SELECT type, answer, COALESCE(explanation,'') AS explanation, score, parent_id "
                "FROM questions WHERE id=:id AND status=1"
            ),
            {"id": payload.question_id},
        ).mappings().first()
        if question is None:
            raise not_found("题目不存在")
        correct = _is_correct(question["type"], question["answer"], payload.answer)
        result = connection.execute(
            text(
                "UPDATE question_records SET answer=:answer, is_correct=:correct, answered=1, "
                "updated_at=:ts WHERE user_id=:uid AND question_id=:qid AND answered=0"
            ),
            {
                "answer": payload.answer.strip(),
                "correct": 1 if correct else 0,
                "ts": now(),
                "uid": user_id,
                "qid": payload.question_id,
            },
        )
        if result.rowcount == 0:
            raise conflict("该题已作答或未领取")
        first = connection.execute(
            text(
                "SELECT COUNT(*) FROM question_first_answers WHERE user_id=:uid AND question_id=:qid"
            ),
            {"uid": user_id, "qid": payload.question_id},
        ).scalar()
        if not first:
            connection.execute(
                text(
                    "INSERT INTO question_first_answers(user_id, question_id, answer, is_correct, "
                    "answered_at) VALUES(:uid, :qid, :answer, :correct, :ts)"
                ),
                {
                    "uid": user_id,
                    "qid": payload.question_id,
                    "answer": payload.answer.strip(),
                    "correct": 1 if correct else 0,
                    "ts": now(),
                },
            )
        stats = _stats(connection, user_id)
    return ok(
        {
            "correct": correct,
            "correct_answer": question["answer"],
            "explanation": question["explanation"],
            "score": question["score"] if correct else 0,
            "question_score": question["score"],
            "answered_count": stats["answered_count"],
            "correct_count": stats["correct_count"],
            "wrong_count": stats["wrong_count"],
        }
    )


@router.post("/questions/restart")
def restart_practice(request: Request):
    with get_engine().begin() as connection:
        user_id = actor_id(request)
        connection.execute(text("DELETE FROM question_records WHERE user_id=:uid"), {"uid": user_id})
    return ok({"reset": True})


@router.get("/questions/wrong")
def wrong_questions(request: Request):
    page, size = page_params(request)
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        total = connection.execute(
            text(
                "SELECT COUNT(*) FROM question_first_answers fa JOIN questions q ON q.id=fa.question_id "
                "WHERE fa.user_id=:uid AND fa.is_correct=0 AND q.status=1"
            ),
            {"uid": user_id},
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.score, fa.answer, fa.answered_at "
                "FROM question_first_answers fa JOIN questions q ON q.id=fa.question_id "
                "WHERE fa.user_id=:uid AND fa.is_correct=0 AND q.status=1 "
                "ORDER BY fa.answered_at DESC LIMIT :limit OFFSET :offset"
            ),
            {"uid": user_id, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["first_answer"] = item.pop("answer")
        item["first_answered_at"] = item.pop("answered_at")
        items.append(item)
    return ok(page_result(items, total, page, size))


@router.get("/questions/wrong/{question_id}")
def wrong_detail(question_id: int, request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        row = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.answer correct_answer, "
                "COALESCE(q.explanation,'') explanation, fa.answer user_answer, fa.is_correct "
                "FROM questions q LEFT JOIN question_first_answers fa "
                "ON fa.question_id=q.id AND fa.user_id=:uid WHERE q.id=:qid"
            ),
            {"uid": user_id, "qid": question_id},
        ).mappings().first()
        connection.commit()
    if row is None:
        raise not_found("题目不存在")
    return ok(dict(row))


@router.post("/questions/wrong/retry/start")
def start_retry(request: Request):
    with get_engine().begin() as connection:
        user_id = actor_id(request)
        rows = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.score, q.category_id "
                "FROM question_first_answers fa JOIN questions q ON q.id=fa.question_id "
                "WHERE fa.user_id=:uid AND fa.is_correct=0 AND q.status=1 ORDER BY fa.answered_at"
            ),
            {"uid": user_id},
        ).mappings().all()
        if not rows:
            raise validation("暂无错题可重练")
        attempt_id = connection.execute(
            text(
                "INSERT INTO question_retry_attempts(user_id, status, question_count, started_at) "
                "VALUES(:uid, 0, :count, :ts)"
            ),
            {"uid": user_id, "count": len(rows), "ts": now()},
        ).lastrowid
    return ok(
        {
            "attempt_id": attempt_id,
            "questions": [dict(r) for r in rows],
            "question_count": len(rows),
        }
    )


@router.post("/questions/wrong/retry/answer")
def submit_retry(payload: RetryAnswerInput, request: Request):
    if payload.attempt_id <= 0 or payload.question_id <= 0 or not payload.answer.strip():
        raise validation("请作答后再提交")
    with named_lock(f"wrong_retry:{payload.attempt_id}:{payload.question_id}") as connection:
        user_id = actor_id(request)
        valid = connection.execute(
            text(
                "SELECT COUNT(*) FROM question_retry_attempts a "
                "JOIN question_first_answers fa ON fa.user_id=a.user_id AND fa.question_id=:qid "
                "AND fa.is_correct=0 WHERE a.id=:aid AND a.user_id=:uid AND a.status=0"
            ),
            {"qid": payload.question_id, "aid": payload.attempt_id, "uid": user_id},
        ).scalar()
        if not valid:
            raise not_found("重练批次不存在")
        question = connection.execute(
            text("SELECT type, answer FROM questions WHERE id=:id AND status=1"),
            {"id": payload.question_id},
        ).mappings().first()
        if question is None:
            raise not_found("题目不存在")
        exists = connection.execute(
            text(
                "SELECT COUNT(*) FROM question_retry_answers WHERE attempt_id=:aid AND question_id=:qid"
            ),
            {"aid": payload.attempt_id, "qid": payload.question_id},
        ).scalar()
        if exists:
            raise conflict("该题已重练")
        correct = _is_correct(question["type"], question["answer"], payload.answer)
        connection.execute(
            text(
                "INSERT INTO question_retry_answers(attempt_id, user_id, question_id, answer, "
                "is_correct, answered_at) VALUES(:aid, :uid, :qid, :answer, :correct, :ts)"
            ),
            {
                "aid": payload.attempt_id,
                "uid": user_id,
                "qid": payload.question_id,
                "answer": payload.answer.strip(),
                "correct": 1 if correct else 0,
                "ts": now(),
            },
        )
        counts = connection.execute(
            text(
                "SELECT COUNT(*), CAST(COALESCE(SUM(is_correct),0) AS SIGNED) FROM question_retry_answers "
                "WHERE attempt_id=:aid"
            ),
            {"aid": payload.attempt_id},
        ).first()
        target = connection.execute(
            text("SELECT question_count FROM question_retry_attempts WHERE id=:aid"),
            {"aid": payload.attempt_id},
        ).scalar()
        completed = counts[0] >= target
        if completed:
            connection.execute(
                text(
                    "UPDATE question_retry_attempts SET status=1, completed_at=:ts WHERE id=:aid"
                ),
                {"ts": now(), "aid": payload.attempt_id},
            )
    return ok(
        {
            "correct": correct,
            "correct_answer": question["answer"],
            "answered_count": counts[0],
            "correct_count": counts[1],
            "wrong_count": counts[0] - counts[1],
            "completed": completed,
        }
    )


# ==================== 题库管理 ====================


@admin_router.get("/questions")
def admin_list(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    question_type = (request.query_params.get("type") or "").strip()
    categories = [int(c) for c in request.query_params.getlist("category_id") if c.isdigit()]
    status = (request.query_params.get("status") or "").strip()
    where = ["q.parent_id=0"]
    params: dict = {}
    if keyword:
        where.append("q.title LIKE :kw")
        params["kw"] = f"%{keyword}%"
    if question_type:
        where.append("q.type=:type")
        params["type"] = question_type
    if categories:
        placeholders = ",".join(f":cat{i}" for i in range(len(categories)))
        where.append(f"q.category_id IN ({placeholders})")
        for index, value in enumerate(categories):
            params[f"cat{index}"] = value
    if status in ("0", "1", "2"):
        where.append("q.status=:status")
        params["status"] = int(status)
    clause = " AND ".join(where)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM questions q WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.answer, COALESCE(q.explanation,'') explanation, "
                "q.status, q.category_id, q.score, q.created_at, q.updated_at, "
                "(SELECT qc.name FROM question_categories qc WHERE qc.id=q.category_id) category_name, "
                "(SELECT COUNT(*) FROM questions c WHERE c.parent_id=q.id) child_count "
                f"FROM questions q WHERE {clause} ORDER BY q.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([dict(r) for r in rows], total, page, size))


@admin_router.get("/questions/options")
def admin_options(request: Request):
    question_type = (request.query_params.get("type") or "").strip()
    category = request.query_params.get("category_id")
    where = ["parent_id=0"]
    params: dict = {}
    if question_type:
        where.append("type=:type")
        params["type"] = question_type
    if category and category.isdigit():
        where.append("category_id=:category")
        params["category"] = int(category)
    clause = " AND ".join(where)
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT q.id, q.type, q.title, q.options, q.status, q.category_id, q.score, "
                "(SELECT COUNT(*) FROM questions c WHERE c.parent_id=q.id AND c.status=1) child_count "
                f"FROM questions q WHERE {clause} ORDER BY q.id DESC LIMIT 1000"
            ),
            params,
        ).mappings().all()
        connection.commit()
    return ok({"items": [dict(r) for r in rows]})


@admin_router.get("/question/{question_id}")
def admin_get(question_id: int):
    with get_engine().connect() as connection:
        question = connection.execute(
            text(
                "SELECT id, type, title, options, answer, COALESCE(explanation,'') explanation, "
                "status, category_id, parent_id, sort_order, score FROM questions WHERE id=:id"
            ),
            {"id": question_id},
        ).mappings().first()
        if question is None:
            raise not_found("题目不存在")
        children = connection.execute(
            text(
                "SELECT id, type, title, options, answer, COALESCE(explanation,'') explanation, "
                "status, category_id, parent_id, sort_order, score FROM questions "
                "WHERE parent_id=:id ORDER BY sort_order, id"
            ),
            {"id": question_id},
        ).mappings().all()
        connection.commit()
    return ok({"question": dict(question), "children": [dict(c) for c in children]})


def _insert_children(connection, parent_id: int, category_id: int, children: list[dict]) -> None:
    for index, child in enumerate(children, start=1):
        child_type = (child.get("type") or "").strip()
        title = (child.get("title") or "").strip()
        if not child_type or not title:
            continue
        _validate_type(child_type)
        connection.execute(
            text(
                "INSERT INTO questions(type, title, options, answer, explanation, status, category_id, "
                "parent_id, sort_order, score, created_at, updated_at) VALUES(:type, :title, "
                ":options, :answer, :explanation, :status, :category_id, :parent_id, :sort_order, "
                ":score, :ts, :ts)"
            ),
            {
                "type": child_type,
                "title": title,
                "options": child.get("options", ""),
                "answer": child.get("answer", ""),
                "explanation": child.get("explanation", ""),
                "status": 1,
                "category_id": category_id,
                "parent_id": parent_id,
                "sort_order": index,
                "score": max(int(child.get("score", 1) or 1), 1),
                "ts": now(),
            },
        )


@admin_router.post("/question")
def admin_create(payload: QuestionInput):
    _validate_type(payload.type)
    title = payload.title.strip()
    if not title:
        raise validation("题目标题不能为空")
    if payload.type == "group" and not payload.children:
        raise validation("综合题至少需要一个子题")
    with named_lock("question:create") as connection:
        timestamp = now()
        is_group = payload.type == "group"
        question_id = connection.execute(
            text(
                "INSERT INTO questions(type, title, options, answer, explanation, status, category_id, "
                "parent_id, sort_order, score, created_at, updated_at) VALUES(:type, :title, :options, "
                ":answer, :explanation, :status, :category_id, 0, 0, :score, :ts, :ts)"
            ),
            {
                "type": payload.type,
                "title": title,
                "options": "" if is_group else payload.options,
                "answer": "" if is_group else payload.answer,
                "explanation": "" if is_group else payload.explanation,
                "status": 1 if payload.status != 0 else 0,
                "category_id": payload.category_id,
                "score": 0 if is_group else max(payload.score, 1),
                "ts": timestamp,
            },
        ).lastrowid
        if is_group:
            _insert_children(connection, question_id, payload.category_id, payload.children)
    return ok({"id": question_id})


@admin_router.put("/question")
def admin_update(payload: QuestionInput):
    if not payload.id:
        raise validation("缺少题目 ID")
    _validate_type(payload.type)
    with named_lock(f"question:update:{payload.id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM questions WHERE id=:id"), {"id": payload.id}
        ).scalar()
        if not exists:
            raise not_found("题目不存在")
        is_group = payload.type == "group"
        fields = [
            "type=:type",
            "options=:options",
            "answer=:answer",
            "explanation=:explanation",
            "status=:status",
            "category_id=:category_id",
            "score=:score",
            "updated_at=:ts",
        ]
        params: dict = {
            "type": payload.type,
            "options": "" if is_group else payload.options,
            "answer": "" if is_group else payload.answer,
            "explanation": "" if is_group else payload.explanation,
            "status": 1 if payload.status != 0 else 0,
            "category_id": payload.category_id,
            "score": 0 if is_group else max(payload.score, 1),
            "ts": now(),
            "id": payload.id,
        }
        if payload.title.strip():
            fields.append("title=:title")
            params["title"] = payload.title.strip()
        connection.execute(
            text(f"UPDATE questions SET {', '.join(fields)} WHERE id=:id"), params
        )
        connection.execute(text("DELETE FROM questions WHERE parent_id=:id"), {"id": payload.id})
        if is_group:
            _insert_children(connection, payload.id, payload.category_id, payload.children)
    return ok({"id": payload.id})


@admin_router.post("/question/toggle-status")
def admin_toggle_status(payload: StatusInput):
    """启用/禁用题目；综合题同时联动其子题，保证练习与考试口径一致。"""
    if payload.status not in (0, 1):
        raise validation("状态不合法")
    with named_lock(f"question:status:{payload.id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM questions WHERE id=:id"), {"id": payload.id}
        ).scalar()
        if not exists:
            raise not_found("题目不存在")
        connection.execute(
            text("UPDATE questions SET status=:status, updated_at=:ts WHERE id=:id"),
            {"status": payload.status, "ts": now(), "id": payload.id},
        )
        connection.execute(
            text("UPDATE questions SET status=:status, updated_at=:ts WHERE parent_id=:id"),
            {"status": payload.status, "ts": now(), "id": payload.id},
        )
    return ok({"id": payload.id, "status": payload.status})


@admin_router.delete("/question/{question_id}")
def admin_delete(question_id: int):
    with named_lock(f"question:delete:{question_id}") as connection:
        targets = f"(SELECT {question_id} UNION SELECT id FROM questions WHERE parent_id={question_id})"
        connection.execute(
            text(f"DELETE FROM question_retry_answers WHERE question_id IN {targets}")
        )
        connection.execute(
            text(f"DELETE FROM question_first_answers WHERE question_id IN {targets}")
        )
        connection.execute(text(f"DELETE FROM question_records WHERE question_id IN {targets}"))
        connection.execute(text("DELETE FROM questions WHERE parent_id=:id"), {"id": question_id})
        result = connection.execute(
            text("DELETE FROM questions WHERE id=:id"), {"id": question_id}
        )
        if result.rowcount == 0:
            raise not_found("题目不存在")
    return ok({"id": question_id})


@admin_router.post("/questions/batch-delete")
def admin_batch_delete(payload: dict):
    ids = payload.get("ids") or []
    if not ids:
        raise validation("请选择要删除的题目")
    with get_engine().begin() as connection:
        for question_id in ids:
            targets = f"(SELECT {int(question_id)} UNION SELECT id FROM questions WHERE parent_id={int(question_id)})"
            connection.execute(text(f"DELETE FROM question_retry_answers WHERE question_id IN {targets}"))
            connection.execute(text(f"DELETE FROM question_first_answers WHERE question_id IN {targets}"))
            connection.execute(text(f"DELETE FROM question_records WHERE question_id IN {targets}"))
            connection.execute(text("DELETE FROM questions WHERE parent_id=:id"), {"id": question_id})
            connection.execute(text("DELETE FROM questions WHERE id=:id"), {"id": question_id})
    return ok({"deleted_count": len(ids)})


@admin_router.get("/question-categories")
def admin_categories():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, name, parent_id, sort_order, status, created_at, updated_at "
                "FROM question_categories ORDER BY parent_id, sort_order, id"
            )
        ).mappings().all()
        connection.commit()
    return ok({"items": [dict(r) for r in rows]})


@admin_router.post("/question-category")
def create_category(payload: CategoryInput):
    name = payload.name.strip()
    if not name:
        raise validation("练习类型名称不能为空")
    with named_lock("question_category:create") as connection:
        category_id = connection.execute(
            text(
                "INSERT INTO question_categories(name, parent_id, sort_order, status, created_at, "
                "updated_at) VALUES(:name, :parent_id, :sort_order, :status, :ts, :ts)"
            ),
            {
                "name": name,
                "parent_id": payload.parent_id,
                "sort_order": payload.sort_order,
                "status": 1 if payload.status != 0 else 0,
                "ts": now(),
            },
        ).lastrowid
    return ok({"id": category_id})


@admin_router.put("/question-category")
def update_category(payload: CategoryInput):
    if not payload.id:
        raise validation("缺少练习类型 ID")
    name = payload.name.strip()
    if not name:
        raise validation("练习类型名称不能为空")
    with get_engine().begin() as connection:
        result = connection.execute(
            text(
                "UPDATE question_categories SET name=:name, parent_id=:parent_id, "
                "sort_order=:sort_order, status=:status, updated_at=:ts WHERE id=:id"
            ),
            {
                "name": name,
                "parent_id": payload.parent_id,
                "sort_order": payload.sort_order,
                "status": 1 if payload.status != 0 else 0,
                "ts": now(),
                "id": payload.id,
            },
        )
        if result.rowcount == 0:
            exists = connection.execute(
                text("SELECT COUNT(*) FROM question_categories WHERE id=:id"), {"id": payload.id}
            ).scalar()
            if not exists:
                raise not_found("练习类型不存在")
    return ok({"id": payload.id})


@admin_router.delete("/question-category/{category_id}")
def delete_category(category_id: int):
    with get_engine().begin() as connection:
        connection.execute(
            text("UPDATE questions SET category_id=0 WHERE category_id=:id"), {"id": category_id}
        )
        result = connection.execute(
            text("DELETE FROM question_categories WHERE id=:id"), {"id": category_id}
        )
        if result.rowcount == 0:
            raise not_found("练习类型不存在")
    return ok({"id": category_id})
