"""RBAC：角色与权限目录、角色权限配置、用户角色分配与会话失效。"""

from __future__ import annotations


import re

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..db import named_lock
from ..domain.rbac import (
    DATA_SCOPE_SELF,
    ROLE_SYSTEM_ADMIN,
    data_scope_rank,
    is_valid_data_scope,
)
from ..error import conflict, forbidden, not_found, validation
from ..response import ok
from ..security import now

router = APIRouter(prefix="/api/admin/rbac")

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.\-]{1,99}$")


class CreateRoleInput(BaseModel):
    code: str
    name: str
    description: str = ""
    data_scope: str
    level: int = 100
    status: int = 1


class UpdateRoleInput(BaseModel):
    name: str
    description: str = ""
    data_scope: str
    level: int
    status: int


class SetRolePermissionsInput(BaseModel):
    permission_codes: list[str]


class CreatePermissionInput(BaseModel):
    code: str
    name: str
    description: str = ""
    module: str


class UpdatePermissionInput(BaseModel):
    name: str
    description: str = ""
    module: str
    status: int


class SetUserRolesInput(BaseModel):
    role_codes: list[str]


def _validate_code(value: str) -> None:
    if not _CODE_RE.match(value):
        raise validation("invalid RBAC code")


def _valid_scope(value: str) -> None:
    if not is_valid_data_scope(value):
        raise validation("invalid data_scope")


def _status(value: int) -> int:
    return 1 if value != 0 else 0


def _normalized(values: list[str]) -> list[str]:
    return sorted({v.strip() for v in values if v.strip()})


def _role_dict(row) -> dict:
    return {
        "id": row["id"],
        "code": row["code"],
        "name": row["name"],
        "description": row["description"] or "",
        "data_scope": row["data_scope"],
        "level": row["level"],
        "built_in": bool(row["built_in"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _permission_codes_for_role(connection, role_id: int) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            text(
                "SELECT p.code FROM permissions p JOIN role_permissions rp "
                "ON rp.permission_id = p.id WHERE rp.role_id = :role_id "
                "ORDER BY p.module, p.code"
            ),
            {"role_id": role_id},
        ).fetchall()
    ]


def _find_role(connection, role_id: int):
    row = connection.execute(
        text(
            "SELECT id, code, name, description, data_scope, level, built_in, status, "
            "created_at, updated_at FROM roles WHERE id = :id"
        ),
        {"id": role_id},
    ).mappings().first()
    if row is None:
        raise not_found("role not found")
    return row


def _find_permission(connection, permission_id: int):
    row = connection.execute(
        text(
            "SELECT id, code, name, description, module, built_in, status, created_at, "
            "updated_at FROM permissions WHERE id = :id"
        ),
        {"id": permission_id},
    ).mappings().first()
    if row is None:
        raise not_found("permission not found")
    return row


def _ids_for_codes(connection, table: str, codes: list[str]) -> list[int]:
    if not codes:
        return []
    placeholders = ",".join(f":c{i}" for i in range(len(codes)))
    params = {f"c{i}": code for i, code in enumerate(codes)}
    rows = connection.execute(
        text(f"SELECT id FROM {table} WHERE status = 1 AND code IN ({placeholders})"), params
    ).fetchall()
    ids = [row[0] for row in rows]
    if len(ids) != len(codes):
        raise validation(f"one or more {table} codes are invalid or disabled")
    return ids


def _bump_role_member_epochs(connection, role_id: int) -> None:
    connection.execute(
        text(
            "UPDATE users SET session_epoch = session_epoch + 1 "
            "WHERE id IN (SELECT user_id FROM user_roles WHERE role_id = :role_id)"
        ),
        {"role_id": role_id},
    )


@router.get("/roles")
def list_roles():
    from ..db import get_engine

    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, code, name, description, data_scope, level, built_in, status, "
                "created_at, updated_at FROM roles ORDER BY level, id"
            )
        ).mappings().all()
        items = []
        for row in rows:
            item = _role_dict(row)
            item["permission_codes"] = _permission_codes_for_role(connection, row["id"])
            items.append(item)
        connection.commit()
    return ok({"items": items})


@router.get("/roles/{role_id}")
def get_role(role_id: int):
    from ..db import get_engine

    with get_engine().connect() as connection:
        row = _find_role(connection, role_id)
        item = _role_dict(row)
        item["permission_codes"] = _permission_codes_for_role(connection, role_id)
        connection.commit()
    return ok(item)


@router.post("/roles")
def create_role(payload: CreateRoleInput):
    code = payload.code.strip()
    name = payload.name.strip()
    _validate_code(code)
    if not name:
        raise validation("role name is required")
    _valid_scope(payload.data_scope)
    timestamp = now()
    with named_lock("roles:codes") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM roles WHERE code = :code"), {"code": code}
        ).scalar()
        if exists:
            raise conflict("RBAC code already exists")
        connection.execute(
            text(
                "INSERT INTO roles(code, name, description, data_scope, level, built_in, status, "
                "created_at, updated_at) VALUES(:code, :name, :description, :data_scope, "
                ":level, 0, :status, :created_at, :updated_at)"
            ),
            {
                "code": code,
                "name": name,
                "description": payload.description,
                "data_scope": payload.data_scope,
                "level": max(payload.level, 1),
                "status": _status(payload.status),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        role_id = connection.execute(
            text("SELECT id FROM roles WHERE code = :code"), {"code": code}
        ).scalar()
        row = _find_role(connection, role_id)
        item = _role_dict(row)
        item["permission_codes"] = []
    return ok(item)


@router.put("/roles/{role_id}")
def update_role(role_id: int, payload: UpdateRoleInput):
    name = payload.name.strip()
    if not name:
        raise validation("role name is required")
    _valid_scope(payload.data_scope)
    with named_lock(f"roles:update:{role_id}") as connection:
        current = _find_role(connection, role_id)
        if current["built_in"] and (
            current["data_scope"] != payload.data_scope or current["level"] != payload.level
        ):
            raise forbidden()
        new_status = _status(payload.status)
        if current["code"] == ROLE_SYSTEM_ADMIN and new_status == 0:
            raise forbidden()
        connection.execute(
            text(
                "UPDATE roles SET name = :name, description = :description, data_scope = :scope, "
                "level = :level, status = :status, updated_at = :updated_at WHERE id = :id"
            ),
            {
                "name": name,
                "description": payload.description,
                "scope": payload.data_scope,
                "level": max(payload.level, 1),
                "status": new_status,
                "updated_at": now(),
                "id": role_id,
            },
        )
        if new_status != current["status"]:
            _bump_role_member_epochs(connection, role_id)
    return ok({"id": role_id})


@router.delete("/roles/{role_id}")
def delete_role(role_id: int):
    with named_lock(f"roles:delete:{role_id}") as connection:
        role = _find_role(connection, role_id)
        if role["built_in"]:
            raise forbidden()
        assigned = connection.execute(
            text("SELECT COUNT(*) FROM user_roles WHERE role_id = :role_id"),
            {"role_id": role_id},
        ).scalar()
        if assigned:
            raise conflict("role is assigned to users")
        connection.execute(
            text("DELETE FROM role_permissions WHERE role_id = :role_id"), {"role_id": role_id}
        )
        connection.execute(text("DELETE FROM roles WHERE id = :id"), {"id": role_id})
    return ok({"id": role_id})


@router.put("/roles/{role_id}/permissions")
def set_role_permissions(role_id: int, payload: SetRolePermissionsInput):
    codes = _normalized(payload.permission_codes)
    with named_lock(f"roles:permissions:{role_id}") as connection:
        role = _find_role(connection, role_id)
        if role["code"] == ROLE_SYSTEM_ADMIN:
            raise forbidden()
        permission_ids = _ids_for_codes(connection, "permissions", codes)
        connection.execute(
            text("DELETE FROM role_permissions WHERE role_id = :role_id"), {"role_id": role_id}
        )
        timestamp = now()
        for permission_id in permission_ids:
            connection.execute(
                text(
                    "INSERT INTO role_permissions(role_id, permission_id, created_at) "
                    "VALUES(:role_id, :permission_id, :created_at)"
                ),
                {"role_id": role_id, "permission_id": permission_id, "created_at": timestamp},
            )
        _bump_role_member_epochs(connection, role_id)
    return ok({"id": role_id, "permission_codes": codes})


@router.get("/permissions")
def list_permissions():
    from ..db import get_engine

    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, code, name, description, module, built_in, status, created_at, "
                "updated_at FROM permissions ORDER BY module, code"
            )
        ).mappings().all()
    return ok({"items": [dict(row) for row in rows]})


@router.get("/permissions/{permission_id}")
def get_permission(permission_id: int):
    from ..db import get_engine

    with get_engine().connect() as connection:
        row = _find_permission(connection, permission_id)
        connection.commit()
    return ok(dict(row))


@router.post("/permissions")
def create_permission(payload: CreatePermissionInput):
    code = payload.code.strip()
    name = payload.name.strip()
    module = payload.module.strip()
    _validate_code(code)
    if not name:
        raise validation("permission name is required")
    if not module:
        raise validation("permission module is required")
    timestamp = now()
    with named_lock("permissions:codes") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM permissions WHERE code = :code"), {"code": code}
        ).scalar()
        if exists:
            raise conflict("RBAC code already exists")
        connection.execute(
            text(
                "INSERT INTO permissions(code, name, description, module, built_in, status, "
                "created_at, updated_at) VALUES(:code, :name, :description, :module, 0, 1, "
                ":created_at, :updated_at)"
            ),
            {
                "code": code,
                "name": name,
                "description": payload.description,
                "module": module,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        permission_id = connection.execute(
            text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
        ).scalar()
        row = _find_permission(connection, permission_id)
    return ok(dict(row))


@router.put("/permissions/{permission_id}")
def update_permission(permission_id: int, payload: UpdatePermissionInput):
    name = payload.name.strip()
    module = payload.module.strip()
    if not name:
        raise validation("permission name is required")
    if not module:
        raise validation("permission module is required")
    with named_lock(f"permissions:update:{permission_id}") as connection:
        _find_permission(connection, permission_id)
        connection.execute(
            text(
                "UPDATE permissions SET name = :name, description = :description, "
                "module = :module, status = :status, updated_at = :updated_at WHERE id = :id"
            ),
            {
                "name": name,
                "description": payload.description,
                "module": module,
                "status": _status(payload.status),
                "updated_at": now(),
                "id": permission_id,
            },
        )
    return ok({"id": permission_id})


@router.delete("/permissions/{permission_id}")
def delete_permission(permission_id: int):
    with named_lock(f"permissions:delete:{permission_id}") as connection:
        permission = _find_permission(connection, permission_id)
        if permission["built_in"]:
            raise forbidden()
        connection.execute(
            text("DELETE FROM role_permissions WHERE permission_id = :id"), {"id": permission_id}
        )
        connection.execute(text("DELETE FROM permissions WHERE id = :id"), {"id": permission_id})
    return ok({"id": permission_id})


@router.get("/users")
def list_rbac_users():
    from ..db import get_engine

    with get_engine().connect() as connection:
        rows = connection.execute(
            text("SELECT id, username, display_name FROM users ORDER BY id DESC LIMIT 500")
        ).mappings().all()
    return ok({"items": [dict(row) for row in rows]})


def _user_profile(connection, user_id: int) -> dict:
    roles = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.code FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :id AND r.status = 1 ORDER BY r.level, r.id"
            ),
            {"id": user_id},
        ).fetchall()
    ]
    permissions = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT DISTINCT p.code FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN roles r ON r.id = rp.role_id AND r.status = 1 "
                "JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :id AND p.status = 1 ORDER BY p.code"
            ),
            {"id": user_id},
        ).fetchall()
    ]
    scopes = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.data_scope FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :id AND r.status = 1"
            ),
            {"id": user_id},
        ).fetchall()
    ]
    data_scope = max(scopes, key=data_scope_rank) if scopes else DATA_SCOPE_SELF
    return {"roles": roles, "permissions": permissions, "data_scope": data_scope}


@router.get("/users/{user_id}/roles")
def get_user_roles(user_id: int):
    from ..db import get_engine

    with get_engine().connect() as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM users WHERE id = :id"), {"id": user_id}
        ).scalar()
        if not exists:
            raise not_found("user not found")
        profile = _user_profile(connection, user_id)
        connection.commit()
    return ok(profile)


@router.put("/users/{user_id}/roles")
def set_user_roles(user_id: int, payload: SetUserRolesInput, request: Request):
    # The acting user comes from the session; the admin middleware already
    # validated permissions, so here we only protect the last super admin.
    from ..db import get_engine
    from ..security import SESSION_COOKIE, authenticate

    raw = request.cookies.get(SESSION_COOKIE)
    with get_engine().connect() as connection:
        actor_session, _ = authenticate(connection, raw)
        actor_id = actor_session.user_id
        connection.commit()

    codes = _normalized(payload.role_codes)
    if not codes:
        raise validation("at least one role is required")
    with named_lock(f"users:roles:{user_id}") as connection:
        exists = connection.execute(
            text("SELECT COUNT(*) FROM users WHERE id = :id"), {"id": user_id}
        ).scalar()
        if not exists:
            raise not_found("user not found")
        role_ids = _ids_for_codes(connection, "roles", codes)
        keeps_admin = ROLE_SYSTEM_ADMIN in codes
        was_admin = connection.execute(
            text(
                "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id AND r.code = :code"
            ),
            {"id": user_id, "code": ROLE_SYSTEM_ADMIN},
        ).scalar()
        if was_admin and not keeps_admin:
            if actor_id == user_id:
                raise forbidden()
            count = connection.execute(
                text(
                    "SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur "
                    "JOIN roles r ON r.id = ur.role_id WHERE r.code = :code"
                ),
                {"code": ROLE_SYSTEM_ADMIN},
            ).scalar()
            if count <= 1:
                raise forbidden()
        connection.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": user_id})
        timestamp = now()
        for role_id in role_ids:
            connection.execute(
                text(
                    "INSERT INTO user_roles(user_id, role_id, created_at) "
                    "VALUES(:user_id, :role_id, :created_at)"
                ),
                {"user_id": user_id, "role_id": role_id, "created_at": timestamp},
            )
        connection.execute(
            text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
            {"id": user_id},
        )
    return ok({"user_id": user_id, "role_codes": codes})
