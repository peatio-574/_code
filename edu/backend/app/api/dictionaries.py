"""字典：字典类型与字典项 CRUD、启停、内置保护与前台启用项读取。"""

from __future__ import annotations


import re

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import now
from ..db import get_engine, named_lock
from ..error import conflict, forbidden, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api")

CODE_RE = re.compile(r"^[a-z0-9_]{1,64}$")


class TypeInput(BaseModel):
    code: str = ""
    name: str
    description: str = ""
    status: int = 1
    sort_order: int = 0


class ItemInput(BaseModel):
    type_id: int
    code: str = ""
    name: str
    description: str = ""
    status: int = 1
    sort_order: int = 0


class ToggleInput(BaseModel):
    id: int
    status: int


class IdsInput(BaseModel):
    ids: list[int]


def _type_view(row) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "description": row["description"] or "",
        "status": row["status"],
        "sort_order": row["sort_order"],
        "built_in": bool(row["built_in"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _item_view(row) -> dict:
    return {
        "id": row["id"],
        "type_id": row["type_id"],
        "code": row["code"],
        "name": row["name"],
        "description": row["description"] or "",
        "status": row["status"],
        "sort_order": row["sort_order"],
        "built_in": bool(row["built_in"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/admin/dictionary-types")
def list_types():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_types ORDER BY sort_order, id"
            )
        ).mappings().all()
        item_rows = connection.execute(
            text(
                "SELECT type_id, name FROM dictionary_items "
                "ORDER BY type_id, sort_order, id"
            )
        ).mappings().all()
        connection.commit()
    names: dict[int, list[str]] = {}
    for item in item_rows:
        names.setdefault(item["type_id"], []).append(item["name"])
    items = []
    for row in rows:
        view = _type_view(row)
        view["item_names"] = names.get(row["id"], [])
        items.append(view)
    return ok({"items": items})


@router.post("/admin/dictionary-types")
def create_type(payload: TypeInput, request: Request):
    code = payload.code.strip()
    name = payload.name.strip()
    if not CODE_RE.match(code):
        raise validation("字典类型编码只能包含小写字母、数字和下划线，长度 1-64")
    if not name:
        raise validation("字典类型名称不能为空")
    with named_lock("dictionary:codes") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if connection.execute(
            text("SELECT COUNT(*) FROM dictionary_types WHERE code=:code"), {"code": code}
        ).scalar():
            raise conflict("字典类型编码已存在")
        timestamp = now()
        type_id = connection.execute(
            text(
                "INSERT INTO dictionary_types(code, name, description, status, sort_order, "
                "built_in, created_by, updated_by, created_at, updated_at) VALUES(:code, :name, "
                ":description, :status, :sort_order, 0, :actor, :actor, :ts, :ts)"
            ),
            {
                "code": code,
                "name": name,
                "description": payload.description.strip(),
                "status": 1 if payload.status else 0,
                "sort_order": payload.sort_order,
                "actor": actor,
                "ts": timestamp,
            },
        ).lastrowid
        row = connection.execute(
            text(
                "SELECT id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_types WHERE id=:id"
            ),
            {"id": type_id},
        ).mappings().first()
    return ok(_type_view(row))


@router.put("/admin/dictionary-types/{type_id}")
def update_type(type_id: int, payload: TypeInput):
    if payload.name is not None and not payload.name.strip():
        raise validation("字典类型名称不能为空")
    with named_lock(f"dictionary:type:{type_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_types WHERE id=:id"), {"id": type_id}
        ).scalar()
        if not exists:
            raise not_found("字典类型不存在")
        fields = ["updated_at=:ts"]
        params: dict = {"ts": now(), "id": type_id}
        if payload.name:
            fields.append("name=:name")
            params["name"] = payload.name.strip()
        fields.append("description=:description")
        params["description"] = payload.description.strip()
        fields.append("status=:status")
        params["status"] = 1 if payload.status else 0
        fields.append("sort_order=:sort_order")
        params["sort_order"] = payload.sort_order
        connection.execute(
            text(f"UPDATE dictionary_types SET {', '.join(fields)} WHERE id=:id"), params
        )
        row = connection.execute(
            text(
                "SELECT id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_types WHERE id=:id"
            ),
            {"id": type_id},
        ).mappings().first()
    return ok(_type_view(row))


@router.post("/admin/dictionary-types/toggle-status")
def toggle_type(payload: ToggleInput):
    with get_engine().begin() as connection:
        result = connection.execute(
            text("UPDATE dictionary_types SET status=:status, updated_at=:ts WHERE id=:id"),
            {"status": 1 if payload.status else 0, "ts": now(), "id": payload.id},
        )
        if result.rowcount == 0:
            raise not_found("字典类型不存在")
    return ok({"id": payload.id, "status": 1 if payload.status else 0})


@router.delete("/admin/dictionary-types/{type_id}")
def delete_type(type_id: int):
    with named_lock(f"dictionary:type:delete:{type_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_types WHERE id=:id"), {"id": type_id}
        ).scalar()
        if not exists:
            raise not_found("字典类型不存在")
        items = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_items WHERE type_id=:id"), {"id": type_id}
        ).scalar()
        if items:
            raise conflict("该类型下仍有字典项，请先删除或停用")
        connection.execute(text("DELETE FROM dictionary_types WHERE id=:id"), {"id": type_id})
    return ok({"id": type_id})


@router.post("/admin/dictionary-types/batch-delete")
def batch_delete_types(payload: IdsInput):
    if not payload.ids:
        raise validation("请选择要删除的字典")
    with named_lock("dictionary:types:batch-delete") as connection:
        for type_id in payload.ids:
            exists = connection.execute(
                text("SELECT COUNT(*) FROM dictionary_types WHERE id=:id"), {"id": type_id}
            ).scalar()
            if not exists:
                raise not_found("字典类型不存在")
            items = connection.execute(
                text("SELECT COUNT(*) FROM dictionary_items WHERE type_id=:id"), {"id": type_id}
            ).scalar()
            if items:
                raise conflict("该类型下仍有字典项，请先删除或停用")
            connection.execute(text("DELETE FROM dictionary_types WHERE id=:id"), {"id": type_id})
    return ok({"deleted_count": len(payload.ids)})


@router.get("/admin/dictionary-types/{type_id}/items")
def list_items(type_id: int):
    with get_engine().connect() as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_types WHERE id=:id"), {"id": type_id}
        ).scalar()
        if not exists:
            raise not_found("字典类型不存在")
        rows = connection.execute(
            text(
                "SELECT id, type_id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_items WHERE type_id=:id "
                "ORDER BY sort_order, id"
            ),
            {"id": type_id},
        ).mappings().all()
        connection.commit()
    return ok({"items": [_item_view(r) for r in rows]})


@public_router.get("/dictionaries/{code}/items")
def list_enabled_items(code: str):
    with get_engine().connect() as connection:
        type_id = connection.execute(
            text(
                "SELECT id FROM dictionary_types WHERE code=:code AND status=1"
            ),
            {"code": code},
        ).scalar()
        if type_id is None:
            raise not_found("字典类型不存在或已停用")
        rows = connection.execute(
            text(
                "SELECT id, type_id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_items WHERE type_id=:id AND status=1 "
                "ORDER BY sort_order, id"
            ),
            {"id": type_id},
        ).mappings().all()
        connection.commit()
    return ok({"items": [_item_view(r) for r in rows]})


def _assert_sort_unique(
    connection, type_id: int, sort_order: int, exclude_id: int | None = None
) -> None:
    """校验同一字典下排序值唯一（各字典之间相互隔离）。"""
    sql = "SELECT COUNT(*) FROM dictionary_items WHERE type_id=:tid AND sort_order=:sort"
    params: dict = {"tid": type_id, "sort": sort_order}
    if exclude_id is not None:
        sql += " AND id<>:id"
        params["id"] = exclude_id
    if connection.execute(text(sql), params).scalar():
        raise conflict("排序值已存在，请使用其他序号")


def _next_item_code(connection, type_id: int) -> str:
    """为不含编码的枚举值生成稳定的内部编码。"""
    index = 1
    while True:
        code = f"item_{index}"
        exists = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_items WHERE type_id=:tid AND code=:code"),
            {"tid": type_id, "code": code},
        ).scalar()
        if not exists:
            return code
        index += 1


@router.post("/admin/dictionary-items")
def create_item(payload: ItemInput):
    code = payload.code.strip()
    name = payload.name.strip()
    if code and not CODE_RE.match(code):
        raise validation("字典项编码只能包含小写字母、数字和下划线，长度 1-64")
    if not name:
        raise validation("字典项名称不能为空")
    with named_lock("dictionary:codes") as connection:
        type_ok = connection.execute(
            text("SELECT COUNT(*) FROM dictionary_types WHERE id=:id"), {"id": payload.type_id}
        ).scalar()
        if not type_ok:
            raise not_found("字典类型不存在")
        _assert_sort_unique(connection, payload.type_id, payload.sort_order)
        if not code:
            code = _next_item_code(connection, payload.type_id)
        elif connection.execute(
            text(
                "SELECT COUNT(*) FROM dictionary_items WHERE type_id=:tid AND code=:code"
            ),
            {"tid": payload.type_id, "code": code},
        ).scalar():
            raise conflict("该类型下字典项编码已存在")
        timestamp = now()
        item_id = connection.execute(
            text(
                "INSERT INTO dictionary_items(type_id, code, name, description, status, "
                "sort_order, built_in, created_at, updated_at) VALUES(:tid, :code, :name, "
                ":description, :status, :sort_order, 0, :ts, :ts)"
            ),
            {
                "tid": payload.type_id,
                "code": code,
                "name": name,
                "description": payload.description.strip(),
                "status": 1 if payload.status else 0,
                "sort_order": payload.sort_order,
                "ts": timestamp,
            },
        ).lastrowid
        row = connection.execute(
            text(
                "SELECT id, type_id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_items WHERE id=:id"
            ),
            {"id": item_id},
        ).mappings().first()
    return ok(_item_view(row))


@router.put("/admin/dictionary-items/{item_id}")
def update_item(item_id: int, payload: ItemInput):
    with named_lock(f"dictionary:item:{item_id}") as connection:
        current = connection.execute(
            text("SELECT type_id FROM dictionary_items WHERE id=:id"), {"id": item_id}
        ).first()
        if current is None:
            raise not_found("字典项不存在")
        _assert_sort_unique(connection, current[0], payload.sort_order, exclude_id=item_id)
        fields = ["updated_at=:ts"]
        params: dict = {"ts": now(), "id": item_id}
        if payload.name and payload.name.strip():
            fields.append("name=:name")
            params["name"] = payload.name.strip()
        fields.append("description=:description")
        params["description"] = payload.description.strip()
        fields.append("status=:status")
        params["status"] = 1 if payload.status else 0
        fields.append("sort_order=:sort_order")
        params["sort_order"] = payload.sort_order
        connection.execute(
            text(f"UPDATE dictionary_items SET {', '.join(fields)} WHERE id=:id"), params
        )
        row = connection.execute(
            text(
                "SELECT id, type_id, code, name, description, status, sort_order, built_in, "
                "created_at, updated_at FROM dictionary_items WHERE id=:id"
            ),
            {"id": item_id},
        ).mappings().first()
    return ok(_item_view(row))


@router.post("/admin/dictionary-items/toggle-status")
def toggle_item(payload: ToggleInput):
    with get_engine().begin() as connection:
        result = connection.execute(
            text("UPDATE dictionary_items SET status=:status, updated_at=:ts WHERE id=:id"),
            {"status": 1 if payload.status else 0, "ts": now(), "id": payload.id},
        )
        if result.rowcount == 0:
            raise not_found("字典项不存在")
    return ok({"id": payload.id, "status": 1 if payload.status else 0})


@router.post("/admin/dictionary-items/reorder")
def reorder_items(payload: IdsInput):
    if not payload.ids:
        raise validation("缺少排序数据")
    timestamp = now()
    with named_lock("dictionary:items:reorder") as connection:
        for index, item_id in enumerate(payload.ids, start=1):
            connection.execute(
                text("UPDATE dictionary_items SET sort_order=:sort, updated_at=:ts WHERE id=:id"),
                {"sort": index, "ts": timestamp, "id": item_id},
            )
    return ok({"ids": payload.ids})


@router.delete("/admin/dictionary-items/{item_id}")
def delete_item(item_id: int):
    with named_lock(f"dictionary:item:delete:{item_id}") as connection:
        row = connection.execute(
            text(
                "SELECT di.built_in, dt.code FROM dictionary_items di "
                "JOIN dictionary_types dt ON dt.id=di.type_id WHERE di.id=:id"
            ),
            {"id": item_id},
        ).first()
        if row is None:
            raise not_found("字典项不存在")
        if row[1] == "course_type":
            code = connection.execute(
                text("SELECT code FROM dictionary_items WHERE id=:id"), {"id": item_id}
            ).scalar()
            used = connection.execute(
                text("SELECT COUNT(*) FROM courses WHERE course_type_code=:code"), {"code": code}
            ).scalar()
            if used:
                raise conflict("该课程类型正被课程使用，无法删除")
        connection.execute(text("DELETE FROM dictionary_items WHERE id=:id"), {"id": item_id})
    return ok({"id": item_id})
