"""控制台总览：活跃学员、已发布课程/考试、近七天学习与待处理内容。

超级管理员看到全站数据；校长/班主任仅看到其所属校区的数据。
"""

from __future__ import annotations


from fastapi import APIRouter, Request
from sqlalchemy import text

from ..common import actor_id, is_super_admin
from ..config import get_settings
from ..db import get_engine
from ..response import ok

router = APIRouter(prefix="/api")


def _campus_scope(connection, actor: int) -> tuple[bool, str]:
    """返回（是否超管，校区过滤 SQL 片段 csv）。

    非超管时返回其有效校区的 id 列表字符串；无校区返回空串（由调用方置为 1=0）。
    """
    is_super = is_super_admin(connection, actor)
    if is_super:
        return True, ""
    campus_ids = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT DISTINCT cm.campus_id FROM campus_members cm "
                "JOIN campuses c ON c.id=cm.campus_id "
                "WHERE cm.user_id=:actor AND cm.status=1 AND c.status=1"
            ),
            {"actor": actor},
        ).fetchall()
    ]
    return False, ",".join(str(int(c)) for c in campus_ids)


@router.get("/admin/dashboard")
def admin_overview(request: Request):
    with get_engine().connect() as connection:
        actor = actor_id(request)
        is_super, csv = _campus_scope(connection, actor)

        if is_super:
            student_filter = "u.status=1"
            course_filter = "status=1"
            exam_filter = "status=1 AND is_mock=0"
            announcement_filter = "status=0"
            pending_course = "status<>1"
            pending_exam = "status=0 AND is_mock=0"
            activity_filter = "1=1"
            task_course = "1=1"
            task_exam = "1=1"
            task_announcement = "1=1"
        elif csv:
            student_filter = (
                f"u.status=1 AND u.id IN (SELECT user_id FROM campus_members "
                f"WHERE status=1 AND campus_id IN ({csv}))"
            )
            # 课程/公告：未指定校区视为平台公共内容，指定校区则按校区隔离
            course_filter = f"status=1 AND (campus_id IS NULL OR campus_id=0 OR campus_id IN ({csv}))"
            exam_filter = (
                f"status=1 AND is_mock=0 AND created_by IN "
                f"(SELECT user_id FROM campus_members WHERE status=1 AND campus_id IN ({csv}))"
            )
            announcement_filter = f"status=0 AND (campus_id IS NULL OR campus_id=0 OR campus_id IN ({csv}))"
            pending_course = f"status<>1 AND (campus_id IS NULL OR campus_id=0 OR campus_id IN ({csv}))"
            pending_exam = (
                f"status=0 AND is_mock=0 AND created_by IN "
                f"(SELECT user_id FROM campus_members WHERE status=1 AND campus_id IN ({csv}))"
            )
            activity_filter = (
                f"user_id IN (SELECT user_id FROM campus_members "
                f"WHERE status=1 AND campus_id IN ({csv}))"
            )
            task_course = f"(campus_id IS NULL OR campus_id=0 OR campus_id IN ({csv}))"
            task_exam = (
                f"created_by IN (SELECT user_id FROM campus_members "
                f"WHERE status=1 AND campus_id IN ({csv}))"
            )
            task_announcement = f"(campus_id IS NULL OR campus_id=0 OR campus_id IN ({csv}))"
        else:
            student_filter = "1=0"
            course_filter = "1=0"
            exam_filter = "1=0"
            announcement_filter = "1=0"
            pending_course = "1=0"
            pending_exam = "1=0"
            activity_filter = "1=0"
            task_course = "1=0"
            task_exam = "1=0"
            task_announcement = "1=0"

        metrics = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM users u JOIN user_roles ur ON ur.user_id=u.id "
                " JOIN roles r ON r.id=ur.role_id AND r.code='student' AND r.status=1 "
                f" WHERE {student_filter}) active_students, "
                f"(SELECT COUNT(*) FROM courses WHERE {course_filter}) published_courses, "
                f"(SELECT COUNT(*) FROM exams WHERE {exam_filter}) published_exams"
            )
        ).mappings().first()
        pending = connection.execute(
            text(
                f"SELECT (SELECT COUNT(*) FROM courses WHERE {pending_course}) + "
                f"(SELECT COUNT(*) FROM exams WHERE {pending_exam}) + "
                f"(SELECT COUNT(*) FROM announcements WHERE {announcement_filter}) pending_content"
            )
        ).scalar()
        activity = connection.execute(
            text(
                "SELECT DATE(FROM_UNIXTIME(last_watched_at)) day, "
                "COUNT(DISTINCT user_id) active_students "
                "FROM course_watch_progress "
                "WHERE last_watched_at >= UNIX_TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY)) "
                f"AND {activity_filter} "
                "GROUP BY day ORDER BY day"
            )
        ).mappings().all()
        tasks = connection.execute(
            text(
                "SELECT '课程' kind, name title, '内容管理' owner, '待发布' status, updated_at, '/admin/courses' url "
                f"FROM courses WHERE status<>1 AND {task_course} "
                "UNION ALL SELECT '考试', title, '考试管理', '草稿', updated_at, '/admin/exams' "
                f"FROM exams WHERE status=0 AND is_mock=0 AND {task_exam} "
                "UNION ALL SELECT '公告', title, '平台运营', '待发布', created_at, '/admin/announcements' "
                f"FROM announcements WHERE status=0 AND {task_announcement} "
                "ORDER BY updated_at DESC LIMIT 6"
            )
        ).mappings().all()
        unfinished = connection.execute(
            text("SELECT COUNT(*) FROM file_uploads WHERE status=0")
        ).scalar()
        connection.commit()
    return ok(
        {
            "metrics": {
                **dict(metrics),
                "pending_content": pending,
            },
            "activity": [dict(a) for a in activity],
            "tasks": [dict(t) for t in tasks],
            "unfinished_uploads": unfinished,
            "exams_ending_today": 0,
            "storage_provider": get_settings().storage_dir and "local",
            "scope": "all" if is_super else "campus",
        }
    )
