"""通知公告：后台 CRUD、发布/置顶切换，前台仅展示已发布公告。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import actor_id, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api")

# 列表/详情公共字段（含更新时间）
_FIELDS = (
    "a.id, a.title, a.content, a.status, a.top, a.created_at, a.updated_at, "
    "a.created_user, a.published_at, "
    "(SELECT COUNT(DISTINCT ar.user_id) FROM announcement_reads ar "
    " WHERE ar.announcement_id = a.id) read_count"
)


class AnnouncementInput(BaseModel):
    title: str
    content: str
    status: int = 0


class AnnouncementUpdate(BaseModel):
    id: int
    title: str | None = None
    content: str | None = None
    status: int | None = None


class ToggleInput(BaseModel):
    id: int
    status: int


class ToggleTopInput(BaseModel):
    id: int
    top: int


class ReadInput(BaseModel):
    ids: list[int] = []


def _view(row, audience: int = 0) -> dict:
    read_count = int(row["read_count"] or 0)
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "status": row["status"],
        "top": row["top"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "created_user": row["created_user"],
        "published_at": row["published_at"],
        "read_count": read_count,
        "unread_count": max(audience - read_count, 0) if audience else 0,
    }


def _active_user_count(connection) -> int:
    """公告的应读人数：所有启用中的账号。"""
    return int(
        connection.execute(text("SELECT COUNT(*) FROM users WHERE status = 1")).scalar() or 0
    )


def _query(request: Request, status_only_published: bool):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    status = request.query_params.get("status")
    top = request.query_params.get("top")
    where = ["1=1"]
    params: dict = {}
    if status_only_published:
        where.append("a.status = 1")
    elif status in ("0", "1"):
        where.append("a.status = :status")
        params["status"] = int(status)
    if top in ("0", "1"):
        where.append("a.top = :top")
        params["top"] = int(top)
    if keyword:
        where.append("a.title LIKE :kw")
        params["kw"] = f"%{keyword}%"
    return page, size, " AND ".join(where), params


@router.get("/admin/announcements")
def list_admin(request: Request):
    page, size, clause, params = _query(request, False)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM announcements a WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                f"SELECT {_FIELDS} FROM announcements a WHERE {clause} "
                "ORDER BY a.top DESC, a.created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        audience = _active_user_count(connection)
        connection.commit()
    return ok(page_result([_view(r, audience) for r in rows], total, page, size))


@public_router.get("/announcements/")
def list_public(request: Request):
    page, size, clause, params = _query(request, True)
    with get_engine().connect() as connection:
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM announcements a WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                f"SELECT {_FIELDS} FROM announcements a WHERE {clause} "
                "ORDER BY a.top DESC, a.created_at DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([_view(r) for r in rows], total, page, size))


@public_router.get("/announcements/{announcement_id}")
def get_public(announcement_id: int):
    with get_engine().connect() as connection:
        row = connection.execute(
            text(f"SELECT {_FIELDS} FROM announcements a WHERE a.id=:id AND a.status=1"),
            {"id": announcement_id},
        ).mappings().first()
        connection.commit()
    if row is None:
        raise not_found("公告不存在")
    return ok(_view(row))


@public_router.post("/announcement/read")
def mark_read(payload: ReadInput, request: Request):
    """将指定公告标记为当前用户已读（幂等）。"""
    ids = [int(value) for value in payload.ids if int(value) > 0]
    if not ids:
        return ok({"read": 0})
    user_id = actor_id(request)
    timestamp = now()
    recorded = 0
    with named_lock(f"announcement:read:{user_id}") as connection:
        for announcement_id in ids:
            exists = connection.execute(
                text(
                    "SELECT id FROM announcement_reads "
                    "WHERE announcement_id=:aid AND user_id=:uid LIMIT 1"
                ),
                {"aid": announcement_id, "uid": user_id},
            ).scalar()
            if exists:
                continue
            connection.execute(
                text(
                    "INSERT INTO announcement_reads(announcement_id, user_id, read_at) "
                    "VALUES(:aid, :uid, :ts)"
                ),
                {"aid": announcement_id, "uid": user_id, "ts": timestamp},
            )
            recorded += 1
    return ok({"read": recorded})


@router.post("/admin/announcement")
def create(payload: AnnouncementInput, request: Request):
    title = payload.title.strip()
    content = payload.content.strip()
    if not title or not content:
        raise validation("标题和内容不能为空")
    if payload.status not in (0, 1):
        raise validation("状态不合法")
    with named_lock("announcement:create") as connection:
        from ..common import actor_primary_campus

        actor = actor_id(request)
        timestamp = now()
        campus_id = actor_primary_campus(connection, actor)
        announcement_id = connection.execute(
            text(
                "INSERT INTO announcements(title, content, status, top, created_at, updated_at, "
                "created_user, published_at, campus_id) VALUES(:title, :content, :status, 0, "
                ":created_at, :created_at, :created_user, :published_at, :campus_id)"
            ),
            {
                "title": title,
                "content": content,
                "status": payload.status,
                "created_at": timestamp,
                "created_user": actor,
                "published_at": timestamp if payload.status == 1 else 0,
                "campus_id": campus_id,
            },
        ).lastrowid
        row = connection.execute(
            text(f"SELECT {_FIELDS} FROM announcements a WHERE a.id=:id"),
            {"id": announcement_id},
        ).mappings().first()
        audience = _active_user_count(connection)
    return ok(_view(row, audience))


@router.put("/admin/announcement")
def update(payload: AnnouncementUpdate):
    if payload.id <= 0:
        raise validation("缺少公告 ID")
    with named_lock(f"announcement:update:{payload.id}") as connection:
        current = connection.execute(
            text("SELECT status FROM announcements WHERE id=:id"), {"id": payload.id}
        ).first()
        if current is None:
            raise not_found("公告不存在")
        fields = ["updated_at=:updated_at"]
        params: dict = {"id": payload.id, "updated_at": now()}
        if payload.title is not None:
            if not payload.title.strip():
                raise validation("标题不能为空")
            fields.append("title=:title")
            params["title"] = payload.title.strip()
        if payload.content is not None:
            if not payload.content.strip():
                raise validation("内容不能为空")
            fields.append("content=:content")
            params["content"] = payload.content.strip()
        if payload.status is not None:
            if payload.status not in (0, 1):
                raise validation("状态不合法")
            fields.append("status=:status")
            params["status"] = payload.status
            if payload.status == 1 and current[0] != 1:
                fields.append("published_at=:published_at")
                params["published_at"] = now()
        connection.execute(
            text(f"UPDATE announcements SET {', '.join(fields)} WHERE id=:id"), params
        )
        row = connection.execute(
            text(f"SELECT {_FIELDS} FROM announcements a WHERE a.id=:id"),
            {"id": payload.id},
        ).mappings().first()
        audience = _active_user_count(connection)
    return ok(_view(row, audience))


@router.post("/admin/announcement/toggle-status")
def toggle_status(payload: ToggleInput):
    if payload.status not in (0, 1):
        raise validation("状态不合法")
    with get_engine().begin() as connection:
        current = connection.execute(
            text("SELECT status FROM announcements WHERE id=:id"), {"id": payload.id}
        ).scalar()
        if current is None:
            raise not_found("公告不存在")
        timestamp = now()
        if payload.status == 1 and current != 1:
            connection.execute(
                text(
                    "UPDATE announcements SET status=1, published_at=:ts, updated_at=:ts "
                    "WHERE id=:id"
                ),
                {"ts": timestamp, "id": payload.id},
            )
        else:
            connection.execute(
                text(
                    "UPDATE announcements SET status=:status, updated_at=:ts WHERE id=:id"
                ),
                {"status": payload.status, "ts": timestamp, "id": payload.id},
            )
    return ok({"id": payload.id, "status": payload.status})


@router.post("/admin/announcement/toggle-top")
def toggle_top(payload: ToggleTopInput):
    if payload.top not in (0, 1):
        raise validation("置顶值不合法")
    with get_engine().begin() as connection:
        result = connection.execute(
            text("UPDATE announcements SET top=:top, updated_at=:ts WHERE id=:id"),
            {"top": payload.top, "ts": now(), "id": payload.id},
        )
        if result.rowcount == 0:
            raise not_found("公告不存在")
    return ok({"id": payload.id, "top": payload.top})


@router.delete("/admin/announcement/{announcement_id}")
def delete(announcement_id: int):
    with get_engine().begin() as connection:
        result = connection.execute(
            text("DELETE FROM announcements WHERE id=:id"), {"id": announcement_id}
        )
        if result.rowcount == 0:
            raise not_found("公告不存在")
        connection.execute(
            text("DELETE FROM announcement_reads WHERE announcement_id=:id"),
            {"id": announcement_id},
        )
    return ok({"id": announcement_id})
