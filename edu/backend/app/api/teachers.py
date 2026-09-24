"""教师管理：教师资料 CRUD 与启停（教师仅作课程资料，不设登录账号）。"""

from __future__ import annotations


from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import not_found, validation
from ..response import ok

router = APIRouter(prefix="/api/admin")


class TeacherInput(BaseModel):
    id: int | None = None
    name: str = ""
    description: str = ""
    avatar: str = ""
    status: int = 1


def _teacher_view(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "avatar": row["avatar"] or "",
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _get(connection, teacher_id: int) -> dict:
    row = connection.execute(
        text(
            "SELECT id, name, description, avatar, status, created_at, updated_at "
            "FROM teachers WHERE id=:id"
        ),
        {"id": teacher_id},
    ).mappings().first()
    if row is None:
        raise not_found("教师不存在")
    return _teacher_view(row)


@router.get("/teachers")
def list_teachers(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    status = (request.query_params.get("status") or "").strip()
    with get_engine().connect() as connection:
        where = ["1=1"]
        params: dict = {}
        if keyword:
            where.append("(name LIKE :kw OR description LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if status in ("0", "1"):
            where.append("status = :status")
            params["status"] = int(status)
        clause = " AND ".join(where)
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM teachers WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT id, name, description, avatar, status, created_at, updated_at "
                f"FROM teachers WHERE {clause} ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        connection.commit()
    return ok(page_result([_teacher_view(r) for r in rows], total, page, size))


@router.post("/teacher")
def create_teacher(payload: TeacherInput, request: Request):
    name = payload.name.strip()
    if not name:
        raise validation("教师姓名不能为空")
    with named_lock("teachers:create") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        timestamp = now()
        teacher_id = connection.execute(
            text(
                "INSERT INTO teachers(name, description, avatar, status, created_by, updated_by, "
                "created_at, updated_at) VALUES(:name, :description, :avatar, :status, :actor, "
                ":actor, :ts, :ts)"
            ),
            {
                "name": name,
                "description": payload.description.strip(),
                "avatar": payload.avatar.strip(),
                "status": 1 if payload.status else 0,
                "actor": actor,
                "ts": timestamp,
            },
        ).lastrowid
        result = _get(connection, teacher_id)
    return ok(result)


@router.put("/teacher")
def update_teacher(payload: TeacherInput, request: Request):
    if not payload.id:
        raise validation("缺少教师 ID")
    with named_lock(f"teachers:update:{payload.id}") as connection:
        fields = ["updated_at = :ts"]
        params: dict = {"ts": now(), "id": payload.id}
        if payload.name.strip():
            fields.append("name = :name")
            params["name"] = payload.name.strip()
        fields.append("description = :description")
        params["description"] = payload.description.strip()
        fields.append("avatar = :avatar")
        params["avatar"] = payload.avatar.strip()
        fields.append("status = :status")
        params["status"] = 1 if payload.status else 0
        result = connection.execute(
            text(f"UPDATE teachers SET {', '.join(fields)} WHERE id=:id"), params
        )
        if result.rowcount == 0:
            exists = connection.execute(
                text("SELECT COUNT(*) FROM teachers WHERE id=:id"), {"id": payload.id}
            ).scalar()
            if not exists:
                raise not_found("教师不存在")
        result = _get(connection, payload.id)
    return ok(result)


@router.delete("/teacher/{teacher_id}")
def delete_teacher(teacher_id: int):
    with named_lock(f"teachers:delete:{teacher_id}") as connection:
        row = connection.execute(
            text("SELECT id FROM teachers WHERE id=:id"), {"id": teacher_id}
        ).scalar()
        if row is None:
            raise not_found("教师不存在")
        connection.execute(
            text("DELETE FROM course_teachers WHERE teacher_id=:id"), {"id": teacher_id}
        )
        connection.execute(text("DELETE FROM teachers WHERE id=:id"), {"id": teacher_id})
    return ok({"id": teacher_id})


@router.post("/teacher/toggle-status")
def toggle_teacher(payload: TeacherInput):
    if not payload.id:
        raise validation("缺少教师 ID")
    with get_engine().begin() as connection:
        result = connection.execute(
            text("UPDATE teachers SET status=:status, updated_at=:ts WHERE id=:id"),
            {"status": 1 if payload.status else 0, "ts": now(), "id": payload.id},
        )
        if result.rowcount == 0:
            raise not_found("教师不存在")
    return ok({"id": payload.id, "status": 1 if payload.status else 0})


@router.post("/teachers/batch-delete")
def batch_delete(payload: dict):
    ids = payload.get("ids") or []
    if not ids:
        raise validation("请选择要删除的教师")
    with get_engine().begin() as connection:
        for teacher_id in ids:
            connection.execute(
                text("DELETE FROM course_teachers WHERE teacher_id=:id"), {"id": teacher_id}
            )
            connection.execute(text("DELETE FROM teachers WHERE id=:id"), {"id": teacher_id})
    return ok({"deleted_count": len(ids)})
