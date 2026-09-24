"""报表：按数据范围查询学习记录与学员统计。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from sqlalchemy import text

from ..common import actor_id, is_super_admin, page_params, page_result
from ..db import get_engine
from ..response import ok

router = APIRouter(prefix="/api/admin")


def _scope_clause(connection, actor: int, user_alias: str = "u") -> str:
    from ..domain import data_scope

    scope = data_scope.context(connection, actor)
    return scope.combined_user_predicate(user_alias)


@router.get("/learning-records")
def learning_records(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    student_id = request.query_params.get("student_id")
    course_id = request.query_params.get("course_id")
    completed = request.query_params.get("completed")
    with get_engine().connect() as connection:
        actor = actor_id(request)
        scope = _scope_clause(connection, actor)
        where = [f"({scope})", "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                 "WHERE ur.user_id=u.id AND r.code='student' AND r.status=1)"]
        params: dict = {"actor": actor}
        if keyword:
            where.append("(u.username LIKE :kw OR u.display_name LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if student_id and student_id.isdigit():
            where.append("lp.user_id = :student_id")
            params["student_id"] = int(student_id)
        if course_id and course_id.isdigit():
            where.append("lp.course_id = :course_id")
            params["course_id"] = int(course_id)
        clause = " AND ".join(where)
        base = (
            "FROM learning_progress lp JOIN users u ON u.id=lp.user_id "
            "JOIN courses c ON c.id=lp.course_id "
            "LEFT JOIN (SELECT user_id, course_id, SUM(watched_seconds) watched_seconds, "
            "SUM(completed) completed_chapters, MAX(last_watched_at) last_watched_at "
            "FROM course_watch_progress GROUP BY user_id, course_id) wp "
            "ON wp.user_id=lp.user_id AND wp.course_id=lp.course_id "
            f"WHERE {clause}"
        )
        if completed == "1":
            base += (
                " AND (SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=lp.course_id AND ch.file<>'') > 0 "
                "AND wp.completed_chapters >= (SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=lp.course_id AND ch.file<>'')"
            )
        elif completed == "0":
            base += (
                " AND (wp.completed_chapters IS NULL OR wp.completed_chapters < "
                "(SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=lp.course_id AND ch.file<>''))"
            )
        total = connection.execute(text(f"SELECT COUNT(*) {base}"), params).scalar()
        rows = connection.execute(
            text(
                "SELECT lp.id, lp.user_id, u.username, u.display_name, lp.course_id, c.name course_name, "
                "lp.chapter_id, lp.progress, lp.created_at, lp.updated_at, "
                "CAST(COALESCE(wp.watched_seconds,0) AS SIGNED) watched_seconds, "
                "CAST(COALESCE(wp.completed_chapters,0) AS SIGNED) completed_chapters, "
                "(SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=lp.course_id AND ch.file<>'') total_video_chapters, "
                "COALESCE(wp.last_watched_at,0) last_watched_at "
                f"{base} ORDER BY lp.updated_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([dict(r) for r in rows], total, page, size))


@router.get("/statistics/students")
def statistics(request: Request):
    with get_engine().connect() as connection:
        actor = actor_id(request)
        scope = _scope_clause(connection, actor)
        row = connection.execute(
            text(
                "SELECT "
                "COUNT(*) student_count, "
                "SUM(CASE WHEN u.status=1 THEN 1 ELSE 0 END) active_student_count "
                "FROM users u WHERE "
                "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                "WHERE ur.user_id=u.id AND r.code='student' AND r.status=1) "
                f"AND ({scope})"
            ),
            {"actor": actor},
        ).mappings().first()
        learning = connection.execute(
            text(
                "SELECT COUNT(DISTINCT lp.user_id) learning_student_count "
                "FROM learning_progress lp JOIN users u ON u.id=lp.user_id "
                f"WHERE ({scope})"
            ),
            {"actor": actor},
        ).scalar()
        exams = connection.execute(
            text(
                "SELECT COUNT(*) exam_attempt_count, "
                "SUM(CASE WHEN a.status=1 THEN 1 ELSE 0 END) submitted_exam_count, "
                "CAST(COALESCE(AVG(CASE WHEN a.status=1 THEN a.total_score END),0) AS DOUBLE) average_score "
                "FROM exam_attempts a JOIN users u ON u.id=a.user_id WHERE "
                "EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                "WHERE ur.user_id=u.id AND r.code='student' AND r.status=1) "
                f"AND ({scope})"
            ),
            {"actor": actor},
        ).mappings().first()
        connection.commit()
    return ok(
        {
            "student_count": int(row["student_count"] or 0),
            "active_student_count": int(row["active_student_count"] or 0),
            "learning_student_count": int(learning or 0),
            "exam_attempt_count": int(exams["exam_attempt_count"] or 0),
            "submitted_exam_count": int(exams["submitted_exam_count"] or 0),
            "average_score": float(exams["average_score"] or 0),
        }
    )
