"""课程与学习：课程/章节/分类/笔记 CRUD，课程列表筛选分页与学习起步。"""

from __future__ import annotations


import json

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, actor_primary_campus, is_super_admin, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import forbidden, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin")


class CourseInput(BaseModel):
    id: int | None = None
    name: str = ""
    description: str = ""
    short_description: str = ""
    course_type_code: str = ""
    course_type_codes: list[str] | None = None
    cover: str = ""
    price: float = 0
    description_image: str = ""
    teacher_ids: list[int] = []
    status: int = 1


class StatusInput(BaseModel):
    id: int
    status: int


class ChapterInput(BaseModel):
    title: str = ""
    description: str = ""
    file: str = ""
    duration: float = 0
    teacher_id: int = 0
    sort_order: int = 0


class CourseQueryParams(BaseModel):
    pass


def _validate_course_type(connection, codes: list[str]) -> None:
    for code in codes:
        if not code:
            continue
        ok_row = connection.execute(
            text(
                "SELECT COUNT(*) FROM dictionary_items di JOIN dictionary_types dt ON dt.id=di.type_id "
                "WHERE dt.code='course_type' AND di.code=:code AND di.status=1"
            ),
            {"code": code},
        ).scalar()
        if not ok_row:
            raise validation(f"课程类型不可用：{code}")


def _set_teachers(connection, course_id: int, teacher_ids: list[int]) -> None:
    connection.execute(
        text("DELETE FROM course_teachers WHERE course_id=:id"), {"id": course_id}
    )
    seen: set[int] = set()
    for teacher_id in teacher_ids:
        if teacher_id <= 0 or teacher_id in seen:
            continue
        seen.add(teacher_id)
        exists = connection.execute(
            text("SELECT COUNT(*) FROM teachers WHERE id=:id"), {"id": teacher_id}
        ).scalar()
        if not exists:
            raise validation("存在无效的授课教师")
        connection.execute(
            text("INSERT INTO course_teachers(course_id, teacher_id) VALUES(:cid, :tid)"),
            {"cid": course_id, "tid": teacher_id},
        )


def _list(request: Request, only_published: bool):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    status = request.query_params.get("status")
    type_codes = request.query_params.getlist("course_type_code")
    single = request.query_params.get("course_type_code_single")
    if single:
        type_codes.append(single)
    where = ["1=1"]
    params: dict = {}
    if only_published:
        where.append("c.status = 1")
    elif status in ("0", "1", "2"):
        where.append("c.status = :status")
        params["status"] = int(status)
    if keyword:
        where.append("(c.name LIKE :kw OR c.short_description LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if type_codes:
        clauses = []
        for index, code in enumerate(type_codes):
            if not code:
                continue
            clauses.append(f"FIND_IN_SET(:type{index}, c.course_type_code)")
            params[f"type{index}"] = code
        if clauses:
            where.append("(" + " OR ".join(clauses) + ")")
    clause = " AND ".join(where)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM courses c WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT c.id, c.name, c.short_description, c.course_type_code, c.cover, c.price, "
                "c.duration, c.status, c.published_at, c.created_at, c.updated_at, c.campus_id, "
                "(SELECT COUNT(*) FROM course_chapters ch WHERE ch.course_id=c.id) chapter_count, "
                "(SELECT COALESCE(SUM(ch.duration),0) FROM course_chapters ch WHERE ch.course_id=c.id) total_duration, "
                "(SELECT GROUP_CONCAT(t.name SEPARATOR ',') FROM course_teachers ct "
                " JOIN teachers t ON t.id=ct.teacher_id WHERE ct.course_id=c.id) teacher_names, "
                "(SELECT t.avatar FROM course_teachers ct JOIN teachers t ON t.id=ct.teacher_id "
                " WHERE ct.course_id=c.id ORDER BY t.id LIMIT 1) teacher_avatar, "
                "(SELECT t.id FROM course_teachers ct JOIN teachers t ON t.id=ct.teacher_id "
                " WHERE ct.course_id=c.id ORDER BY t.id LIMIT 1) teacher_id "
                f"FROM courses c WHERE {clause} ORDER BY c.id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["teacher_name"] = row["teacher_names"] or ""
        item["teacher_names"] = (row["teacher_names"] or "").split(",") if row["teacher_names"] else []
        item["price"] = float(row["price"] or 0)
        item["duration"] = float(row["duration"] or 0)
        item["total_duration"] = float(row["total_duration"] or 0)
        items.append(item)
    return page_result(items, total, page, size)


@router.get("/course/")
def list_public(request: Request):
    return ok(_list(request, True))


@router.get("/course/latest")
def list_latest():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT c.id, c.name, c.cover, c.price, c.duration, "
                "(SELECT GROUP_CONCAT(t.name SEPARATOR ',') FROM course_teachers ct "
                " JOIN teachers t ON t.id=ct.teacher_id WHERE ct.course_id=c.id) teacher_name "
                "FROM courses c WHERE c.status=1 AND c.published_at>0 "
                "ORDER BY c.published_at DESC, c.id DESC LIMIT 9"
            )
        ).mappings().all()
        connection.commit()
    return ok({"items": [dict(r) for r in rows]})


@admin_router.get("/courses")
def list_admin(request: Request):
    return ok(_list(request, False))


def _course_value(connection, course_id: int, user_id: int | None = None) -> dict:
    row = connection.execute(
        text(
            "SELECT id, name, description, short_description, course_type_code, cover, price, "
            "duration, status, published_at, description_image, category_id, created_at, created_by, "
            "updated_at, updated_by FROM courses WHERE id=:id"
        ),
        {"id": course_id},
    ).mappings().first()
    if row is None:
        raise not_found("课程不存在")
    course = dict(row)
    course["price"] = float(course["price"] or 0)
    course["duration"] = float(course["duration"] or 0)
    teachers = connection.execute(
        text(
            "SELECT t.id, t.name, t.avatar, t.description FROM course_teachers ct "
            "JOIN teachers t ON t.id=ct.teacher_id WHERE ct.course_id=:id AND t.status=1 ORDER BY t.id"
        ),
        {"id": course_id},
    ).mappings().all()
    chapters = connection.execute(
        text(
            "SELECT id, course_id, title, description, file, duration, teacher_id, sort_order, "
            "created_at, updated_at FROM course_chapters WHERE course_id=:id ORDER BY sort_order, id"
        ),
        {"id": course_id},
    ).mappings().all()
    chapter_list = []
    total_duration = 0.0
    for chapter in chapters:
        item = dict(chapter)
        item["duration"] = float(item["duration"] or 0)
        total_duration += item["duration"]
        chapter_list.append(item)
    learned = 0.0
    if user_id:
        learned = float(
            connection.execute(
                text(
                    "SELECT CAST(COALESCE(SUM(watched_seconds),0) AS SIGNED) FROM course_watch_progress "
                    "WHERE user_id=:user_id AND course_id=:course_id"
                ),
                {"user_id": user_id, "course_id": course_id},
            ).scalar()
            or 0
        )
    return {
        "course": course,
        "teacher_ids": [t["id"] for t in teachers],
        "teachers": [dict(t) for t in teachers],
        "chapters": chapter_list,
        "total_duration": total_duration,
        "learned_duration": learned,
        "rating": 5.0,
    }


@router.get("/course/{course_id}")
def get_course(course_id: int, request: Request):
    user_id = 0
    try:
        user_id = actor_id(request)
    except Exception:
        user_id = 0
    with get_engine().connect() as connection:
        value = _course_value(connection, course_id, user_id)
        connection.commit()
    return ok(value)


@admin_router.get("/course/{course_id}")
def get_course_admin(course_id: int, request: Request):
    with get_engine().connect() as connection:
        value = _course_value(connection, course_id)
        connection.commit()
    return ok(value)


@router.get("/course/{course_id}/chapter/")
def list_chapters(course_id: int):
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, course_id, title, description, file, duration, teacher_id, sort_order, "
                "created_at, updated_at FROM course_chapters WHERE course_id=:id ORDER BY sort_order, id"
            ),
            {"id": course_id},
        ).mappings().all()
        connection.commit()
    items = []
    for row in rows:
        item = dict(row)
        item["duration"] = float(item["duration"] or 0)
        items.append(item)
    return ok({"items": items})


@admin_router.post("/course")
def create_course(payload: CourseInput, request: Request):
    name = payload.name.strip()
    if not name:
        raise validation("课程名称不能为空")
    codes = payload.course_type_codes or ([payload.course_type_code] if payload.course_type_code else [])
    codes = [code for code in codes if code]
    with named_lock("course:create") as connection:
        actor = actor_id(request)
        _validate_course_type(connection, codes)
        campus_id = actor_primary_campus(connection, actor)
        timestamp = now()
        course_id = connection.execute(
            text(
                "INSERT INTO courses(name, description, short_description, category_id, cover, price, "
                "duration, status, published_at, description_image, course_type_code, campus_id, "
                "created_at, created_by, updated_at, updated_by) VALUES(:name, :description, "
                ":short_description, 0, :cover, :price, 0, 2, 0, :description_image, :type_codes, "
                ":campus_id, :created_at, :actor, :updated_at, :actor)"
            ),
            {
                "name": name,
                "description": payload.description,
                "short_description": payload.short_description.strip(),
                "cover": payload.cover.strip(),
                "price": payload.price,
                "description_image": payload.description_image,
                "type_codes": ",".join(codes),
                "campus_id": campus_id,
                "created_at": timestamp,
                "actor": actor,
                "updated_at": timestamp,
            },
        ).lastrowid
        _set_teachers(connection, course_id, payload.teacher_ids)
        value = _course_value(connection, course_id)
    return ok(value)


@admin_router.put("/course")
def update_course(payload: CourseInput, request: Request):
    if not payload.id:
        raise validation("缺少课程 ID")
    codes = payload.course_type_codes or ([payload.course_type_code] if payload.course_type_code else [])
    codes = [code for code in codes if code]
    with named_lock(f"course:update:{payload.id}") as connection:
        current = connection.execute(
            text("SELECT status FROM courses WHERE id=:id"), {"id": payload.id}
        ).first()
        if current is None:
            raise not_found("课程不存在")
        _validate_course_type(connection, codes)
        timestamp = now()
        fields = [
            "description=:description",
            "short_description=:short_description",
            "cover=:cover",
            "price=:price",
            "description_image=:description_image",
            "updated_at=:updated_at",
        ]
        params: dict = {
            "description": payload.description,
            "short_description": payload.short_description.strip(),
            "cover": payload.cover.strip(),
            "price": payload.price,
            "description_image": payload.description_image,
            "updated_at": timestamp,
            "id": payload.id,
        }
        if payload.name.strip():
            fields.append("name=:name")
            params["name"] = payload.name.strip()
        if codes:
            fields.append("course_type_code=:type_codes")
            params["type_codes"] = ",".join(codes)
        if payload.status in (0, 1, 2):
            fields.append("status=:status")
            params["status"] = payload.status
            if payload.status == 1 and current[0] != 1:
                fields.append("published_at=:published_at")
                params["published_at"] = timestamp
        connection.execute(
            text(f"UPDATE courses SET {', '.join(fields)} WHERE id=:id"), params
        )
        _set_teachers(connection, payload.id, payload.teacher_ids)
        value = _course_value(connection, payload.id)
    return ok(value)


@admin_router.post("/course/toggle-status")
def toggle_course(payload: StatusInput):
    if payload.status not in (0, 1, 2):
        raise validation("状态不合法")
    with get_engine().begin() as connection:
        current = connection.execute(
            text("SELECT status FROM courses WHERE id=:id"), {"id": payload.id}
        ).scalar()
        if current is None:
            raise not_found("课程不存在")
        if payload.status == 1 and current != 1:
            connection.execute(
                text("UPDATE courses SET status=1, published_at=:ts, updated_at=:ts WHERE id=:id"),
                {"ts": now(), "id": payload.id},
            )
        else:
            connection.execute(
                text("UPDATE courses SET status=:status, updated_at=:ts WHERE id=:id"),
                {"status": payload.status, "ts": now(), "id": payload.id},
            )
    return ok({"id": payload.id, "status": payload.status})


@admin_router.delete("/course/{course_id}")
def delete_course(course_id: int):
    with named_lock(f"course:delete:{course_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM courses WHERE id=:id"), {"id": course_id}
        ).scalar()
        if not exists:
            raise not_found("课程不存在")
        for statement in (
            "DELETE FROM note_likes WHERE comment_id IN (SELECT id FROM course_notes WHERE course_id=:id)",
            "DELETE FROM course_notes WHERE course_id=:id",
            "DELETE FROM learning_progress WHERE course_id=:id",
            "DELETE FROM course_watch_progress WHERE course_id=:id",
            "DELETE FROM course_watch_sessions WHERE course_id=:id",
            "DELETE FROM course_chapters WHERE course_id=:id",
            "DELETE FROM course_teachers WHERE course_id=:id",
            "DELETE FROM courses WHERE id=:id",
        ):
            connection.execute(text(statement), {"id": course_id})
    return ok({"id": course_id})


@admin_router.post("/courses/batch-delete")
def batch_delete(payload: dict):
    ids = payload.get("ids") or []
    if not ids:
        raise validation("请选择要删除的课程")
    deleted = 0
    with get_engine().begin() as connection:
        for course_id in ids:
            for statement in (
                "DELETE FROM note_likes WHERE comment_id IN (SELECT id FROM course_notes WHERE course_id=:id)",
                "DELETE FROM course_notes WHERE course_id=:id",
                "DELETE FROM learning_progress WHERE course_id=:id",
                "DELETE FROM course_watch_progress WHERE course_id=:id",
                "DELETE FROM course_watch_sessions WHERE course_id=:id",
                "DELETE FROM course_chapters WHERE course_id=:id",
                "DELETE FROM course_teachers WHERE course_id=:id",
                "DELETE FROM courses WHERE id=:id",
            ):
                connection.execute(text(statement), {"id": course_id})
            deleted += 1
    return ok({"deleted_count": deleted})


@admin_router.post("/course/{course_id}/chapter")
def create_chapter(course_id: int, payload: ChapterInput):
    title = payload.title.strip()
    if not title:
        raise validation("章节标题不能为空")
    with get_engine().begin() as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM courses WHERE id=:id"), {"id": course_id}
        ).scalar()
        if not exists:
            raise not_found("课程不存在")
        timestamp = now()
        chapter_id = connection.execute(
            text(
                "INSERT INTO course_chapters(course_id, title, description, file, duration, "
                "teacher_id, sort_order, created_at, updated_at) VALUES(:cid, :title, :description, "
                ":file, :duration, :teacher_id, :sort_order, :ts, :ts)"
            ),
            {
                "cid": course_id,
                "title": title,
                "description": payload.description.strip(),
                "file": payload.file.strip(),
                "duration": payload.duration,
                "teacher_id": payload.teacher_id,
                "sort_order": payload.sort_order,
                "ts": timestamp,
            },
        ).lastrowid
        result = connection.execute(
            text(
                "SELECT id, course_id, title, description, file, duration, teacher_id, sort_order, "
                "created_at, updated_at FROM course_chapters WHERE id=:id"
            ),
            {"id": chapter_id},
        ).mappings().first()
    return ok(dict(result))


@admin_router.put("/course/{course_id}/chapter/{chapter_id}")
def update_chapter(course_id: int, chapter_id: int, payload: ChapterInput):
    with get_engine().begin() as connection:
        fields = [
            "description=:description",
            "file=:file",
            "duration=:duration",
            "teacher_id=:teacher_id",
            "sort_order=:sort_order",
            "updated_at=:ts",
        ]
        params: dict = {
            "description": payload.description.strip(),
            "file": payload.file.strip(),
            "duration": payload.duration,
            "teacher_id": payload.teacher_id,
            "sort_order": payload.sort_order,
            "ts": now(),
            "id": chapter_id,
        }
        if payload.title.strip():
            fields.append("title=:title")
            params["title"] = payload.title.strip()
        result = connection.execute(
            text(f"UPDATE course_chapters SET {', '.join(fields)} WHERE id=:id"), params
        )
        if result.rowcount == 0:
            exists = connection.execute(
                text("SELECT COUNT(*) FROM course_chapters WHERE id=:id"), {"id": chapter_id}
            ).scalar()
            if not exists:
                raise not_found("章节不存在")
        row = connection.execute(
            text(
                "SELECT id, course_id, title, description, file, duration, teacher_id, sort_order, "
                "created_at, updated_at FROM course_chapters WHERE id=:id"
            ),
            {"id": chapter_id},
        ).mappings().first()
    return ok(dict(row))


@admin_router.delete("/course/{course_id}/chapter/{chapter_id}")
def delete_chapter(course_id: int, chapter_id: int):
    with get_engine().begin() as connection:
        connection.execute(
            text("DELETE FROM course_chapters WHERE id=:id"), {"id": chapter_id}
        )
    return ok({"id": chapter_id})


# ==================== 课程分类 ====================


@router.get("/category/")
def list_categories():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, name, parent_id, status, created_at, created_by, updated_at, updated_by "
                "FROM categories ORDER BY id"
            )
        ).mappings().all()
        connection.commit()
    return ok({"items": [dict(r) for r in rows]})


# ==================== 课程笔记 ====================


class NoteInput(BaseModel):
    comment: str
    attachments: str = ""
    parent_id: int = 0


@router.get("/course/{course_id}/notes")
def list_notes(course_id: int, request: Request):
    page, size = page_params(request)
    user_id = 0
    try:
        user_id = actor_id(request)
    except Exception:
        user_id = 0
    with get_engine().connect() as connection:
        total = connection.execute(
            text("SELECT COUNT(*) FROM course_notes WHERE course_id=:id"), {"id": course_id}
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT n.id, n.course_id, n.user_id, n.comment, n.created_time, n.attachments, "
                "n.parent_id, n.like_count, u.username, u.display_name, u.avatar, "
                "EXISTS(SELECT 1 FROM note_likes nl WHERE nl.comment_id=n.id AND nl.user_id=:user_id) is_liked "
                "FROM course_notes n JOIN users u ON u.id=n.user_id WHERE n.course_id=:id "
                "ORDER BY n.created_time DESC, n.id DESC LIMIT :limit OFFSET :offset"
            ),
            {
                "id": course_id,
                "user_id": user_id,
                "limit": size,
                "offset": (page - 1) * size,
            },
        ).mappings().all()
        connection.commit()
    return ok(page_result([dict(r) for r in rows], total, page, size))


@router.post("/course/{course_id}/notes")
def create_note(course_id: int, payload: NoteInput, request: Request):
    comment = payload.comment.strip()
    if not comment:
        raise validation("笔记内容不能为空")
    with get_engine().begin() as connection:
        user_id = actor_id(request)
        status = connection.execute(
            text("SELECT status FROM courses WHERE id=:id"), {"id": course_id}
        ).scalar()
        if status is None:
            raise not_found("课程不存在")
        if status != 1:
            raise not_found("课程未发布")
        if payload.parent_id:
            parent = connection.execute(
                text("SELECT course_id FROM course_notes WHERE id=:id"),
                {"id": payload.parent_id},
            ).scalar()
            if parent != course_id:
                raise validation("父级笔记不属于该课程")
        timestamp = now()
        note_id = connection.execute(
            text(
                "INSERT INTO course_notes(course_id, user_id, comment, created_time, attachments, "
                "parent_id, like_count) VALUES(:cid, :uid, :comment, :ts, :attachments, :parent_id, 0)"
            ),
            {
                "cid": course_id,
                "uid": user_id,
                "comment": comment,
                "ts": timestamp,
                "attachments": payload.attachments,
                "parent_id": payload.parent_id,
            },
        ).lastrowid
    return ok({"id": note_id, "course_id": course_id, "user_id": user_id})


@router.delete("/course/{course_id}/notes/{note_id}")
def delete_note(course_id: int, note_id: int, request: Request):
    with get_engine().begin() as connection:
        user_id = actor_id(request)
        connection.execute(text("DELETE FROM note_likes WHERE comment_id=:id"), {"id": note_id})
        result = connection.execute(
            text("DELETE FROM course_notes WHERE id=:id AND course_id=:cid AND user_id=:uid"),
            {"id": note_id, "cid": course_id, "uid": user_id},
        )
        if result.rowcount == 0:
            raise not_found("笔记不存在")
    return ok({"id": note_id})


@router.post("/course/{course_id}/notes/{note_id}/like")
def toggle_like(course_id: int, note_id: int, request: Request):
    with named_lock(f"note_like:{note_id}") as connection:
        user_id = actor_id(request)
        exists = connection.execute(
            text("SELECT COUNT(*) FROM course_notes WHERE id=:id AND course_id=:cid"),
            {"id": note_id, "cid": course_id},
        ).scalar()
        if not exists:
            raise not_found("笔记不存在")
        liked = connection.execute(
            text("SELECT id FROM note_likes WHERE comment_id=:id AND user_id=:uid"),
            {"id": note_id, "uid": user_id},
        ).scalar()
        if liked:
            connection.execute(text("DELETE FROM note_likes WHERE id=:id"), {"id": liked})
            connection.execute(
                text("UPDATE course_notes SET like_count=GREATEST(like_count-1,0) WHERE id=:id"),
                {"id": note_id},
            )
            is_liked = False
        else:
            connection.execute(
                text(
                    "INSERT INTO note_likes(comment_id, user_id, created_at) VALUES(:id, :uid, :ts)"
                ),
                {"id": note_id, "uid": user_id, "ts": now()},
            )
            connection.execute(
                text("UPDATE course_notes SET like_count=like_count+1 WHERE id=:id"),
                {"id": note_id},
            )
            is_liked = True
        like_count = connection.execute(
            text("SELECT like_count FROM course_notes WHERE id=:id"), {"id": note_id}
        ).scalar()
    return ok({"id": note_id, "is_liked": is_liked, "like_count": like_count})
