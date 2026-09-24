"""控制台总览：活跃学员、已发布课程/考试、近七天学习与待处理内容。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from sqlalchemy import text

from ..common import actor_id, is_super_admin
from ..config import get_settings
from ..db import get_engine
from ..response import ok

router = APIRouter(prefix="/api")


@router.get("/admin/dashboard")
def admin_overview(request: Request):
    with get_engine().connect() as connection:
        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        campus_ids = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT DISTINCT cm.campus_id FROM campus_members cm JOIN campuses c ON c.id=cm.campus_id "
                    "WHERE cm.user_id=:actor AND cm.status=1 AND c.status=1"
                ),
                {"actor": actor},
            ).fetchall()
        ]
        campus_clause = ""
        if not is_super:
            if not campus_ids:
                campus_clause = " AND 1=0"
            else:
                csv = ",".join(str(int(c)) for c in campus_ids)
                campus_clause = f" AND campus_id IN ({csv})"

        metrics = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM users u JOIN user_roles ur ON ur.user_id=u.id "
                " JOIN roles r ON r.id=ur.role_id AND r.code='student' AND r.status=1 "
                " WHERE u.status=1) active_students, "
                "(SELECT COUNT(*) FROM courses WHERE status=1) published_courses, "
                "(SELECT COUNT(*) FROM exams WHERE status=1 AND is_mock=0) published_exams"
            )
        ).mappings().first()
        pending = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(*) FROM courses WHERE status<>1) + "
                "(SELECT COUNT(*) FROM exams WHERE status=0 AND is_mock=0) + "
                "(SELECT COUNT(*) FROM announcements WHERE status=0) pending_content"
            )
        ).scalar()
        activity = connection.execute(
            text(
                "SELECT DATE(FROM_UNIXTIME(last_watched_at)) day, COUNT(DISTINCT user_id) active_students "
                "FROM course_watch_progress WHERE last_watched_at >= UNIX_TIMESTAMP(DATE_SUB(CURDATE(), INTERVAL 6 DAY)) "
                "GROUP BY day ORDER BY day"
            )
        ).mappings().all()
        tasks = connection.execute(
            text(
                "SELECT '课程' kind, name title, '内容管理' owner, '待发布' status, updated_at, '/admin/course' url "
                "FROM courses WHERE status<>1 "
                "UNION ALL SELECT '考试', title, '考试管理', '草稿', updated_at, '/admin/exams' FROM exams WHERE status=0 AND is_mock=0 "
                "UNION ALL SELECT '公告', title, '平台运营', '待发布', created_at, '/admin/announcement' FROM announcements WHERE status=0 "
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
        }
    )
