"""校区管理：校区 CRUD、状态联动、校区成员维护（仅超管可增删校区）。"""

from __future__ import annotations


from fastapi import APIRouter, Path, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..common import is_super_admin, now, page_params, page_result
from ..db import get_engine, named_lock
from ..error import conflict, forbidden, not_found, validation
from ..response import ok

router = APIRouter(prefix="/api/admin/campuses")


class CampusInput(BaseModel):
    code: str = ""
    name: str
    address: str = ""
    contact_name: str = ""
    contact_mobile: str = ""
    manager: str = ""
    contact: str = ""
    status: int = 1


class CampusUpdate(BaseModel):
    code: str | None = None
    name: str | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_mobile: str | None = None
    manager: str | None = None
    contact: str | None = None
    status: int | None = None


class MemberInput(BaseModel):
    user_id: int
    member_type: str
    is_primary: bool = True


class MemberUpdate(BaseModel):
    member_type: str | None = None
    status: int | None = None


class IdsInput(BaseModel):
    ids: list[int]


def _campus_row(row) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "address": row["address"],
        "contact_name": row["contact_name"],
        "contact_mobile": row["contact_mobile"],
        "manager": row["manager"] if "manager" in row else "",
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("")
def list_campuses(request: Request):
    page, size = page_params(request)
    keyword = (request.query_params.get("keyword") or "").strip()
    status = (request.query_params.get("status") or "").strip()
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        where = ["1=1"]
        params: dict = {}
        if not is_super:
            where.append(
                "EXISTS (SELECT 1 FROM campus_members cm WHERE cm.campus_id=c.id "
                "AND cm.user_id=:actor AND cm.member_type='principal' AND cm.status=1)"
            )
            params["actor"] = actor
        if keyword:
            where.append("(c.name LIKE :kw OR c.code LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if status in ("0", "1"):
            where.append("c.status = :status")
            params["status"] = int(status)
        clause = " AND ".join(where)
        total = connection.execute(
            text(f"SELECT COUNT(*) FROM campuses c WHERE {clause}"), params
        ).scalar()
        rows = connection.execute(
            text(
                "SELECT c.id, c.code, c.name, c.address, c.contact_name, c.contact_mobile, "
                "c.status, c.created_at, c.updated_at, "
                "(SELECT COUNT(*) FROM campus_members cm WHERE cm.campus_id=c.id AND cm.status=1) member_count, "
                "(SELECT COUNT(*) FROM campus_members cm WHERE cm.campus_id=c.id AND cm.status=1 AND cm.member_type='principal') principal_count, "
                "(SELECT COUNT(*) FROM campus_members cm WHERE cm.campus_id=c.id AND cm.status=1 AND cm.member_type='student') student_count "
                f"FROM campuses c WHERE {clause} ORDER BY c.id LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": size, "offset": (page - 1) * size},
        ).mappings().all()
        items = []
        for row in rows:
            item = dict(row)
            item["manager"] = ""
            items.append(item)
        connection.commit()
    return ok(page_result(items, total, page, size))


@router.post("")
def create_campus(payload: CampusInput, request: Request):
    name = payload.name.strip()
    if not name:
        raise validation("校区名称不能为空")
    with named_lock("campuses:codes") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if not is_super_admin(connection, actor):
            raise forbidden()
        exists = connection.execute(
            text("SELECT COUNT(*) FROM campuses WHERE name = :name"), {"name": name}
        ).scalar()
        if exists:
            raise conflict("校区名称已存在")
        code = payload.code.strip() or f"CAMP-{now()}"
        connection.execute(
            text(
                "INSERT INTO campuses(code, name, address, contact_name, contact_mobile, "
                "status, created_by, created_at, updated_at) "
                "VALUES(:code, :name, :address, :contact_name, :contact_mobile, :status, "
                ":actor, :created_at, :updated_at)"
            ),
            {
                "code": code,
                "name": name,
                "address": payload.address.strip(),
                "contact_name": (payload.manager or payload.contact_name).strip(),
                "contact_mobile": (payload.contact or payload.contact_mobile).strip(),
                "status": 1 if payload.status else 0,
                "actor": actor,
                "created_at": now(),
                "updated_at": now(),
            },
        )
    return ok({"name": name})


@router.get("/{campus_id}")
def get_campus(campus_id: int, request: Request):
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        row = connection.execute(
            text(
                "SELECT id, code, name, address, contact_name, contact_mobile, status, "
                "created_at, updated_at FROM campuses WHERE id = :id"
            ),
            {"id": campus_id},
        ).mappings().first()
        if row is None:
            raise not_found("校区不存在")
        if not is_super:
            visible = connection.execute(
                text(
                    "SELECT COUNT(*) FROM campus_members WHERE campus_id=:id AND user_id=:actor "
                    "AND member_type='principal' AND status=1"
                ),
                {"id": campus_id, "actor": actor},
            ).scalar()
            if not visible:
                raise not_found("校区不存在")
        connection.commit()
    return ok(dict(row))


@router.put("/{campus_id}")
def update_campus(campus_id: int, payload: CampusUpdate, request: Request):
    with named_lock("campuses:codes") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if not is_super_admin(connection, actor):
            raise forbidden()
        current = connection.execute(
            text("SELECT id FROM campuses WHERE id = :id"), {"id": campus_id}
        ).scalar()
        if current is None:
            raise not_found("校区不存在")
        fields = ["updated_at = :updated_at"]
        params: dict = {"updated_at": now(), "id": campus_id}
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise validation("校区名称不能为空")
            dup = connection.execute(
                text("SELECT COUNT(*) FROM campuses WHERE name = :name AND id <> :id"),
                {"name": name, "id": campus_id},
            ).scalar()
            if dup:
                raise conflict("校区名称已存在")
            fields.append("name = :name")
            params["name"] = name
        for field in ("code", "address", "contact_name", "contact_mobile"):
            value = getattr(payload, field)
            if value is not None:
                fields.append(f"{field} = :{field}")
                params[field] = value.strip()
        if payload.manager is not None:
            fields.append("contact_name = :contact_name")
            params["contact_name"] = payload.manager.strip()
        if payload.contact is not None:
            fields.append("contact_mobile = :contact_mobile")
            params["contact_mobile"] = payload.contact.strip()
        if payload.status is not None:
            fields.append("status = :status")
            params["status"] = 1 if payload.status else 0
        connection.execute(
            text(f"UPDATE campuses SET {', '.join(fields)} WHERE id = :id"), params
        )
    return ok({"id": campus_id})


@router.post("/{campus_id}/toggle-status")
def toggle_status(campus_id: int, request: Request):
    with named_lock(f"campuses:status:{campus_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if not is_super_admin(connection, actor):
            raise forbidden()
        status = connection.execute(
            text("SELECT status FROM campuses WHERE id = :id"), {"id": campus_id}
        ).scalar()
        if status is None:
            raise not_found("校区不存在")
        new_status = 0 if status else 1
        connection.execute(
            text("UPDATE campuses SET status = :status, updated_at = :updated_at WHERE id = :id"),
            {"status": new_status, "updated_at": now(), "id": campus_id},
        )
        # 状态联动：同步该校区所有用户状态，并使其会话失效
        affected = connection.execute(
            text(
                "UPDATE users SET status = :status, session_epoch = session_epoch + 1, "
                "updated_at = :updated_at WHERE id IN "
                "(SELECT user_id FROM campus_members WHERE campus_id = :id AND status = 1)"
            ),
            {"status": new_status, "updated_at": now(), "id": campus_id},
        ).rowcount
    return ok({"id": campus_id, "status": new_status, "affected": affected})


@router.delete("/{campus_id}")
def delete_campus(campus_id: int, request: Request):
    with named_lock(f"campuses:delete:{campus_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if not is_super_admin(connection, actor):
            raise forbidden()
        members = connection.execute(
            text("SELECT COUNT(*) FROM campus_members WHERE campus_id = :id AND status = 1"),
            {"id": campus_id},
        ).scalar()
        if members:
            raise conflict("该校仍有成员，请先移除成员后再删除")
        result = connection.execute(
            text("DELETE FROM campuses WHERE id = :id"), {"id": campus_id}
        )
        if result.rowcount == 0:
            raise not_found("校区不存在")
    return ok({"id": campus_id})


@router.post("/batch-delete")
def batch_delete(payload: IdsInput, request: Request):
    if not payload.ids:
        raise validation("请选择要删除的校区")
    deleted = 0
    skipped = 0
    with get_engine().begin() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        if not is_super_admin(connection, actor):
            raise forbidden()
        for campus_id in payload.ids:
            members = connection.execute(
                text("SELECT COUNT(*) FROM campus_members WHERE campus_id = :id AND status = 1"),
                {"id": campus_id},
            ).scalar()
            if members:
                skipped += 1
                continue
            result = connection.execute(
                text("DELETE FROM campuses WHERE id = :id"), {"id": campus_id}
            )
            deleted += result.rowcount
    return ok({"deleted_count": deleted, "skipped_count": skipped})


def _member_view(row) -> dict:
    return {
        "id": row["id"],
        "campus_id": row["campus_id"],
        "user_id": row["user_id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "member_type": row["member_type"],
        "is_primary": bool(row["is_primary"]),
        "status": row["status"],
        "joined_at": row["joined_at"],
        "left_at": row["left_at"],
    }


@router.get("/{campus_id}/members")
def list_members(campus_id: int, request: Request):
    with get_engine().connect() as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        exists = connection.execute(
            text("SELECT COUNT(*) FROM campuses WHERE id = :id"), {"id": campus_id}
        ).scalar()
        if not exists:
            raise not_found("校区不存在")
        if not is_super:
            visible = connection.execute(
                text(
                    "SELECT COUNT(*) FROM campus_members WHERE campus_id=:id AND user_id=:actor "
                    "AND member_type='principal' AND status=1"
                ),
                {"id": campus_id, "actor": actor},
            ).scalar()
            if not visible:
                raise forbidden()
        rows = connection.execute(
            text(
                "SELECT cm.id, cm.campus_id, cm.user_id, u.username, u.display_name, "
                "cm.member_type, cm.is_primary, cm.status, cm.joined_at, cm.left_at "
                "FROM campus_members cm JOIN users u ON u.id = cm.user_id "
                "WHERE cm.campus_id = :id ORDER BY cm.status DESC, cm.id"
            ),
            {"id": campus_id},
        ).mappings().all()
        connection.commit()
    return ok({"items": [_member_view(row) for row in rows]})


@router.post("/{campus_id}/members")
def add_member(campus_id: int, payload: MemberInput, request: Request):
    from ..domain.campus import VALID_MEMBER_TYPES

    if payload.member_type not in VALID_MEMBER_TYPES:
        raise validation("invalid member_type")
    with named_lock(f"campus:member:{campus_id}:{payload.user_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        if not is_super and not connection.execute(
            text(
                "SELECT COUNT(*) FROM campus_members WHERE campus_id=:id AND user_id=:actor "
                "AND member_type='principal' AND status=1"
            ),
            {"id": campus_id, "actor": actor},
        ).scalar():
            raise forbidden()
        if not is_super and payload.member_type == "principal":
            raise forbidden()
        campus_status = connection.execute(
            text("SELECT status FROM campuses WHERE id = :id"), {"id": campus_id}
        ).scalar()
        if campus_status is None:
            raise not_found("校区不存在")
        if campus_status != 1:
            raise conflict("校区已停用")
        role_ok = connection.execute(
            text(
                "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON r.id=ur.role_id "
                "WHERE ur.user_id=:uid AND r.code=:code AND r.status=1"
            ),
            {"uid": payload.user_id, "code": payload.member_type},
        ).scalar()
        if not role_ok:
            raise validation("成员类型与用户角色不匹配")
        dup = connection.execute(
            text(
                "SELECT COUNT(*) FROM campus_members WHERE campus_id=:cid AND user_id=:uid AND status=1"
            ),
            {"cid": campus_id, "uid": payload.user_id},
        ).scalar()
        if dup:
            raise conflict("该用户已是校区成员")
        if payload.is_primary:
            connection.execute(
                text(
                    "UPDATE campus_members SET is_primary=0 WHERE campus_id=:cid AND user_id=:uid"
                ),
                {"cid": campus_id, "uid": payload.user_id},
            )
        connection.execute(
            text(
                "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, status, "
                "joined_at, created_by, created_at) VALUES(:cid, :uid, :type, :primary, 1, "
                ":joined_at, :actor, :created_at)"
            ),
            {
                "cid": campus_id,
                "uid": payload.user_id,
                "type": payload.member_type,
                "primary": 1 if payload.is_primary else 0,
                "joined_at": now(),
                "actor": actor,
                "created_at": now(),
            },
        )
        connection.execute(
            text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
            {"id": payload.user_id},
        )
    return ok({"campus_id": campus_id, "user_id": payload.user_id})


@router.put("/{campus_id}/members/{user_id}")
def update_member(campus_id: int, user_id: int, payload: MemberUpdate, request: Request):
    from ..domain.campus import VALID_MEMBER_TYPES

    with named_lock(f"campus:member:{campus_id}:{user_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        if not is_super and not connection.execute(
            text(
                "SELECT COUNT(*) FROM campus_members WHERE campus_id=:id AND user_id=:actor "
                "AND member_type='principal' AND status=1"
            ),
            {"id": campus_id, "actor": actor},
        ).scalar():
            raise forbidden()
        current = connection.execute(
            text(
                "SELECT status FROM campus_members WHERE campus_id=:cid AND user_id=:uid "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"cid": campus_id, "uid": user_id},
        ).scalar()
        if current is None:
            raise not_found("成员不存在")
        if payload.member_type is not None:
            if payload.member_type not in VALID_MEMBER_TYPES:
                raise validation("invalid member_type")
            if not is_super and payload.member_type == "principal":
                raise forbidden()
            connection.execute(
                text("UPDATE campus_members SET member_type=:type WHERE campus_id=:cid AND user_id=:uid"),
                {"type": payload.member_type, "cid": campus_id, "uid": user_id},
            )
        if payload.status is not None:
            new_status = 1 if payload.status else 0
            if current == 1 and new_status == 0:
                managing = connection.execute(
                    text("SELECT COUNT(*) FROM users WHERE manager_id = :uid"), {"uid": user_id}
                ).scalar()
                if managing:
                    raise conflict("该用户仍在管理其他学员，不能停用校区成员关系")
                active = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM campus_members WHERE user_id=:uid AND status=1"
                    ),
                    {"uid": user_id},
                ).scalar()
                if active <= 1:
                    raise conflict("用户必须保留至少一个有效校区")
            connection.execute(
                text(
                    "UPDATE campus_members SET status=:status, left_at=:left_at "
                    "WHERE campus_id=:cid AND user_id=:uid"
                ),
                {
                    "status": new_status,
                    "left_at": now() if new_status == 0 else None,
                    "cid": campus_id,
                    "uid": user_id,
                },
            )
        connection.execute(
            text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
            {"id": user_id},
        )
    return ok({"campus_id": campus_id, "user_id": user_id})


@router.delete("/{campus_id}/members/{user_id}")
def delete_member(campus_id: int, user_id: int, request: Request):
    with named_lock(f"campus:member:{campus_id}:{user_id}") as connection:
        from ..common import actor_id

        actor = actor_id(request)
        is_super = is_super_admin(connection, actor)
        if not is_super and not connection.execute(
            text(
                "SELECT COUNT(*) FROM campus_members WHERE campus_id=:id AND user_id=:actor "
                "AND member_type='principal' AND status=1"
            ),
            {"id": campus_id, "actor": actor},
        ).scalar():
            raise forbidden()
        active = connection.execute(
            text(
                "SELECT COUNT(*) FROM campus_members WHERE campus_id=:cid AND user_id=:uid AND status=1"
            ),
            {"cid": campus_id, "uid": user_id},
        ).scalar()
        if not active:
            raise not_found("成员不存在")
        managing = connection.execute(
            text("SELECT COUNT(*) FROM users WHERE manager_id = :uid"), {"uid": user_id}
        ).scalar()
        if managing:
            raise conflict("该用户仍在管理其他学员，不能移除")
        remaining = connection.execute(
            text("SELECT COUNT(*) FROM campus_members WHERE user_id=:uid AND status=1"),
            {"uid": user_id},
        ).scalar()
        if remaining <= 1:
            raise conflict("用户必须保留至少一个有效校区")
        connection.execute(
            text(
                "UPDATE campus_members SET status=0, left_at=:left_at "
                "WHERE campus_id=:cid AND user_id=:uid"
            ),
            {"left_at": now(), "cid": campus_id, "uid": user_id},
        )
        connection.execute(
            text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
            {"id": user_id},
        )
    return ok({"campus_id": campus_id, "user_id": user_id})
