from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, actor_primary_campus, now
from ..db import get_engine, named_lock
from ..domain import watch as watch_rules
from ..error import not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")


class StartInput(BaseModel):
    course_id: int


class WatchStartInput(BaseModel):
    course_id: int
    chapter_id: int
    client_session_id: str


class WatchProgressInput(BaseModel):
    watch_session_id: int
    position_seconds: int
    video_duration_seconds: int
    sequence: int
    event: str


class WatchFinishInput(BaseModel):
    watch_session_id: int
    position_seconds: int | None = None


EVENTS = {"playing", "pause", "seek", "ended", "heartbeat"}


@router.post("/learning/start")
def start_learning(payload: StartInput, request: Request):
    course_id = payload.course_id
    if course_id <= 0:
        raise validation("invalid course id")
    with named_lock(f"learning:{actor_id(request)}:{course_id}") as connection:
        user_id = actor_id(request)
        course = connection.execute(
            text("SELECT id, status FROM courses WHERE id=:id"), {"id": course_id}
        ).first()
        if course is None or course[1] != 1:
            raise not_found("课程不存在或未发布")
        existing = connection.execute(
            text("SELECT id FROM learning_progress WHERE course_id=:cid AND user_id=:uid"),
            {"cid": course_id, "uid": user_id},
        ).scalar()
        if existing is None:
            chapter = connection.execute(
                text(
                    "SELECT id FROM course_chapters WHERE course_id=:cid ORDER BY sort_order, id LIMIT 1"
                ),
                {"cid": course_id},
            ).scalar()
            campus_id = actor_primary_campus(connection, user_id)
            connection.execute(
                text(
                    "INSERT INTO learning_progress(course_id, chapter_id, user_id, progress, "
                    "campus_id, created_at, updated_at) VALUES(:cid, :chapter_id, :uid, 0, "
                    ":campus_id, :ts, :ts)"
                ),
                {
                    "cid": course_id,
                    "chapter_id": chapter or 0,
                    "uid": user_id,
                    "campus_id": campus_id,
                    "ts": now(),
                },
            )
        row = connection.execute(
            text(
                "SELECT id, course_id, chapter_id, user_id, progress, created_at, updated_at "
                "FROM learning_progress WHERE course_id=:cid AND user_id=:uid"
            ),
            {"cid": course_id, "uid": user_id},
        ).mappings().first()
    return ok(dict(row))


@router.post("/learning/watch/start")
def watch_start(payload: WatchStartInput, request: Request):
    if payload.course_id <= 0 or payload.chapter_id <= 0:
        raise validation("invalid course or chapter")
    client_session_id = payload.client_session_id.strip()
    if not (1 <= len(client_session_id) <= 64):
        raise validation("invalid client_session_id")
    with named_lock(f"watch:{actor_id(request)}") as connection:
        user_id = actor_id(request)
        chapter = connection.execute(
            text(
                "SELECT ch.id FROM course_chapters ch JOIN courses c ON c.id=ch.course_id "
                "WHERE ch.id=:chapter_id AND ch.course_id=:course_id AND c.status=1"
            ),
            {"chapter_id": payload.chapter_id, "course_id": payload.course_id},
        ).scalar()
        if chapter is None:
            raise not_found("章节不存在或课程未发布")
        timestamp = now()
        # 关闭超时的旧会话
        connection.execute(
            text(
                "UPDATE course_watch_sessions SET status=2, ended_at=:ts, updated_at=:ts "
                "WHERE user_id=:uid AND status=0 AND last_reported_at < :threshold"
            ),
            {
                "ts": timestamp,
                "uid": user_id,
                "threshold": timestamp - watch_rules.SESSION_IDLE_TIMEOUT_SECONDS,
            },
        )
        existing = connection.execute(
            text(
                "SELECT id FROM course_watch_sessions WHERE user_id=:uid AND "
                "client_session_id=:csid AND status=0"
            ),
            {"uid": user_id, "csid": client_session_id},
        ).scalar()
        progress = connection.execute(
            text(
                "SELECT last_position_seconds, video_duration_seconds, completed "
                "FROM course_watch_progress WHERE user_id=:uid AND course_id=:cid AND chapter_id=:chid"
            ),
            {"uid": user_id, "cid": payload.course_id, "chid": payload.chapter_id},
        ).mappings().first()
        resume = progress["last_position_seconds"] if progress else 0
        completed = bool(progress["completed"]) if progress else False
        if existing is None:
            campus_id = actor_primary_campus(connection, user_id)
            existing = connection.execute(
                text(
                    "INSERT INTO course_watch_sessions(user_id, course_id, chapter_id, "
                    "client_session_id, started_at, last_reported_at, start_position_seconds, "
                    "last_position_seconds, watched_seconds, last_sequence, status, campus_id, "
                    "created_at, updated_at) VALUES(:uid, :cid, :chid, :csid, :ts, :ts, :resume, "
                    ":resume, 0, 0, 0, :campus_id, :ts, :ts)"
                ),
                {
                    "uid": user_id,
                    "cid": payload.course_id,
                    "chid": payload.chapter_id,
                    "csid": client_session_id,
                    "ts": timestamp,
                    "resume": resume,
                    "campus_id": campus_id,
                },
            ).lastrowid
        if progress is None:
            campus_id = actor_primary_campus(connection, user_id)
            connection.execute(
                text(
                    "INSERT INTO course_watch_progress(user_id, course_id, chapter_id, "
                    "first_watched_at, last_watched_at, last_position_seconds, "
                    "video_duration_seconds, watched_seconds, completed, last_report_sequence, "
                    "campus_id, created_at, updated_at) VALUES(:uid, :cid, :chid, :ts, :ts, 0, 0, "
                    "0, 0, 0, :campus_id, :ts, :ts)"
                ),
                {
                    "uid": user_id,
                    "cid": payload.course_id,
                    "chid": payload.chapter_id,
                    "ts": timestamp,
                    "campus_id": campus_id,
                },
            )
    return ok(
        {
            "watch_session_id": existing,
            "resume_seconds": resume,
            "video_duration_seconds": progress["video_duration_seconds"] if progress else 0,
            "completed": completed,
            "report_interval": watch_rules.REPORT_INTERVAL_SECONDS,
        }
    )


@router.post("/learning/watch/progress")
def watch_progress(payload: WatchProgressInput, request: Request):
    if payload.watch_session_id <= 0 or payload.sequence <= 0:
        raise validation("invalid session or sequence")
    if payload.event not in EVENTS:
        raise validation("invalid event")
    if not watch_rules.valid_duration(payload.video_duration_seconds) and payload.video_duration_seconds != 0:
        raise validation("invalid video duration")
    if not watch_rules.valid_position(payload.position_seconds, payload.video_duration_seconds):
        raise validation("invalid position")
    with named_lock(f"watch:{actor_id(request)}") as connection:
        user_id = actor_id(request)
        session = connection.execute(
            text(
                "SELECT id, user_id, course_id, chapter_id, status, last_reported_at, "
                "last_position_seconds, watched_seconds, last_sequence "
                "FROM course_watch_sessions WHERE id=:id AND user_id=:uid"
            ),
            {"id": payload.watch_session_id, "uid": user_id},
        ).mappings().first()
        if session is None:
            raise not_found("观看会话不存在")
        if session["status"] != 0:
            return ok({"accepted": False, "reason": "session_closed"})
        timestamp = now()
        duplicate = payload.sequence <= session["last_sequence"]
        progress = connection.execute(
            text(
                "SELECT completed, watched_seconds, video_duration_seconds "
                "FROM course_watch_progress WHERE user_id=:uid AND course_id=:cid AND chapter_id=:chid"
            ),
            {"uid": user_id, "cid": session["course_id"], "chid": session["chapter_id"]},
        ).mappings().first()
        if duplicate:
            return ok(
                {
                    "accepted": True,
                    "duplicate": True,
                    "watched_seconds": progress["watched_seconds"] if progress else 0,
                    "completed": bool(progress["completed"]) if progress else False,
                }
            )
        if payload.event == "seek":
            delta = 0
        else:
            server_delta = timestamp - session["last_reported_at"]
            position_delta = payload.position_seconds - session["last_position_seconds"]
            delta = watch_rules.effective_seconds(server_delta, position_delta)
        new_watched = (session["watched_seconds"] or 0) + delta
        connection.execute(
            text(
                "UPDATE course_watch_sessions SET last_reported_at=:ts, "
                "last_position_seconds=:position, watched_seconds=:watched, last_sequence=:seq, "
                "updated_at=:ts WHERE id=:id AND status=0"
            ),
            {
                "ts": timestamp,
                "position": payload.position_seconds,
                "watched": new_watched,
                "seq": payload.sequence,
                "id": session["id"],
            },
        )
        duration = payload.video_duration_seconds or (progress["video_duration_seconds"] if progress else 0)
        progress_watched = (progress["watched_seconds"] if progress else 0) + delta
        completed = bool(progress["completed"]) if progress else False
        if watch_rules.is_completed(payload.position_seconds, duration, progress_watched):
            completed = True
        connection.execute(
            text(
                "UPDATE course_watch_progress SET last_position_seconds=:position, "
                "video_duration_seconds=:duration, watched_seconds=:watched, completed=:completed, "
                "last_report_sequence=GREATEST(last_report_sequence, :seq), last_watched_at=:ts, "
                "updated_at=:ts WHERE user_id=:uid AND course_id=:cid AND chapter_id=:chid"
            ),
            {
                "position": payload.position_seconds,
                "duration": duration,
                "watched": progress_watched,
                "completed": 1 if completed else 0,
                "seq": payload.sequence,
                "ts": timestamp,
                "uid": user_id,
                "cid": session["course_id"],
                "chid": session["chapter_id"],
            },
        )
    return ok({"accepted": True, "watched_seconds": progress_watched, "completed": completed})


@router.post("/learning/watch/finish")
def watch_finish(payload: WatchFinishInput, request: Request):
    if payload.watch_session_id <= 0:
        raise validation("invalid session")
    with named_lock(f"watch:{actor_id(request)}") as connection:
        user_id = actor_id(request)
        session = connection.execute(
            text(
                "SELECT id, course_id, chapter_id, status, last_reported_at, last_position_seconds, "
                "watched_seconds FROM course_watch_sessions WHERE id=:id AND user_id=:uid"
            ),
            {"id": payload.watch_session_id, "uid": user_id},
        ).mappings().first()
        if session is None:
            raise not_found("观看会话不存在")
        if session["status"] != 0:
            return ok({"accepted": False, "reason": "session_closed"})
        position = payload.position_seconds if payload.position_seconds is not None else session["last_position_seconds"]
        if position < 0:
            raise validation("invalid position")
        timestamp = now()
        server_delta = timestamp - session["last_reported_at"]
        position_delta = position - session["last_position_seconds"]
        delta = watch_rules.effective_seconds(server_delta, position_delta)
        new_watched = (session["watched_seconds"] or 0) + delta
        connection.execute(
            text(
                "UPDATE course_watch_sessions SET status=1, ended_at=:ts, updated_at=:ts, "
                "watched_seconds=:watched WHERE id=:id"
            ),
            {"ts": timestamp, "watched": new_watched, "id": session["id"]},
        )
        progress = connection.execute(
            text(
                "SELECT watched_seconds, video_duration_seconds, completed FROM course_watch_progress "
                "WHERE user_id=:uid AND course_id=:cid AND chapter_id=:chid"
            ),
            {"uid": user_id, "cid": session["course_id"], "chid": session["chapter_id"]},
        ).mappings().first()
        if progress is not None:
            duration = progress["video_duration_seconds"]
            watched = (progress["watched_seconds"] or 0) + delta
            completed = bool(progress["completed"]) or watch_rules.is_completed(position, duration, watched)
            connection.execute(
                text(
                    "UPDATE course_watch_progress SET last_position_seconds=:position, "
                    "watched_seconds=:watched, completed=:completed, last_watched_at=:ts, "
                    "updated_at=:ts WHERE user_id=:uid AND course_id=:cid AND chapter_id=:chid"
                ),
                {
                    "position": position,
                    "watched": watched,
                    "completed": 1 if completed else 0,
                    "ts": timestamp,
                    "uid": user_id,
                    "cid": session["course_id"],
                    "chid": session["chapter_id"],
                },
            )
        else:
            completed = False
            watched = new_watched
    return ok({"accepted": True, "watched_seconds": watched, "completed": completed})


@router.get("/learning/progress")
def course_progress(request: Request):
    course_id = request.query_params.get("course_id")
    if not course_id or not course_id.isdigit():
        raise validation("invalid course_id")
    course_id = int(course_id)
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        rows = connection.execute(
            text(
                "SELECT chapter_id, completed, last_position_seconds, video_duration_seconds, "
                "watched_seconds, last_watched_at FROM course_watch_progress "
                "WHERE user_id=:uid AND course_id=:cid"
            ),
            {"uid": user_id, "cid": course_id},
        ).mappings().all()
        total_video = connection.execute(
            text(
                "SELECT COUNT(*) FROM course_chapters WHERE course_id=:cid AND file <> ''"
            ),
            {"cid": course_id},
        ).scalar()
        connection.commit()
    chapters = [dict(r) for r in rows]
    completed_chapters = sum(1 for c in chapters if c["completed"])
    ratio = (completed_chapters / total_video) if total_video else 0
    last_chapter_id = 0
    resume = 0
    if chapters:
        latest = max(chapters, key=lambda c: (c["last_watched_at"], c["chapter_id"]))
        last_chapter_id = latest["chapter_id"]
        resume = latest["last_position_seconds"]
    return ok(
        {
            "chapters": chapters,
            "completed_chapters": completed_chapters,
            "total_video_chapters": total_video,
            "completion_ratio": ratio,
            "last_chapter_id": last_chapter_id,
            "resume_seconds": resume,
        }
    )


@router.get("/learning/overview")
def learning_overview(request: Request):
    with get_engine().connect() as connection:
        user_id = actor_id(request)
        summary = connection.execute(
            text(
                "SELECT "
                "(SELECT COUNT(DISTINCT course_id) FROM learning_progress WHERE user_id=:uid) enrolled_courses, "
                "(SELECT COUNT(*) FROM question_first_answers WHERE user_id=:uid) answered_questions, "
                "(SELECT COUNT(*) FROM question_first_answers WHERE user_id=:uid AND is_correct=0) wrong_questions, "
                "(SELECT COUNT(*) FROM exam_attempts WHERE user_id=:uid) exam_attempts, "
                "(SELECT COUNT(*) FROM exam_attempts a JOIN exams e ON e.id=a.exam_id "
                " WHERE a.user_id=:uid AND a.status=1 AND a.total_score>=e.pass_score) passed_exams, "
                "(SELECT CAST(COALESCE(SUM(watched_seconds),0) AS SIGNED) FROM course_watch_progress WHERE user_id=:uid) watched_seconds"
            ),
            {"uid": user_id},
        ).mappings().first()
        recent = connection.execute(
            text(
                "SELECT lp.course_id, c.name course_name, c.cover, lp.chapter_id, "
                "(SELECT ch.title FROM course_chapters ch WHERE ch.id=lp.chapter_id) chapter_title, "
                "lp.progress, lp.updated_at, "
                "(SELECT COUNT(*) FROM course_watch_progress wp WHERE wp.user_id=:uid AND wp.course_id=lp.course_id AND wp.completed=1) completed_chapters, "
                "(SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=lp.course_id AND ch.file<>'') total_chapters, "
                "(SELECT CAST(COALESCE(SUM(watched_seconds),0) AS SIGNED) FROM course_watch_progress wp WHERE wp.user_id=:uid AND wp.course_id=lp.course_id) watched_seconds "
                "FROM learning_progress lp JOIN courses c ON c.id=lp.course_id "
                "WHERE lp.user_id=:uid ORDER BY lp.updated_at DESC LIMIT 3"
            ),
            {"uid": user_id},
        ).mappings().all()
        agenda = connection.execute(
            text(
                "SELECT e.id exam_id, e.title, e.exam_time, e.duration, "
                "COALESCE((SELECT a.id FROM exam_attempts a WHERE a.exam_id=e.id AND a.user_id=:uid "
                "AND a.status=0 ORDER BY a.id DESC LIMIT 1),0) attempt_id "
                "FROM exams e WHERE e.is_mock=0 AND e.status=1 "
                "AND (e.created_by=(SELECT manager_id FROM users WHERE id=:uid) OR EXISTS ("
                "SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=e.created_by "
                "AND r.code='system_admin' AND r.status=1)) ORDER BY e.exam_time DESC LIMIT 3"
            ),
            {"uid": user_id},
        ).mappings().all()
        connection.commit()
    recent_courses = [dict(r) for r in recent]
    return ok(
        {
            "summary": dict(summary),
            "continue_course": recent_courses[0] if recent_courses else None,
            "recent_courses": recent_courses,
            "agenda": [dict(a) for a in agenda],
            "weekly_activity": [],
        }
    )
