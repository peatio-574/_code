"""启动种子数据。

幂等写入内置角色、权限、角色-权限矩阵、四类测试账号与默认校区，
并保证现有账号的主校区成员关系。可重复执行，不覆盖既有数据。
"""
from __future__ import annotations

from sqlalchemy import text

from .db import get_engine, named_lock
from .domain.rbac import (
    BUILTIN_PERMISSIONS,
    BUILTIN_ROLES,
    get_builtin_role_permissions,
)
from .security import hash_password, now

# 测试账号统一初始密码
TEST_PASSWORD = "Test123!"

TEST_USERS: list[tuple[str, str, str]] = [
    ("test_system_admin", "system_admin", "Test System Admin"),
    ("test_principal", "principal", "Test Principal"),
    ("test_homeroom_teacher", "homeroom_teacher", "Test Homeroom Teacher"),
    ("test_student", "student", "Test Student"),
]


def seed_rbac() -> None:
    """Idempotently seeds built-in roles, permissions, test users, and campus."""
    password_hash = hash_password(TEST_PASSWORD)
    with named_lock("seed:rbac") as connection:
        timestamp = now()

        # 1. Upsert built-in roles.
        for role in BUILTIN_ROLES:
            existing = connection.execute(
                text("SELECT id FROM roles WHERE code = :code"), {"code": role.code}
            ).scalar()
            if existing:
                connection.execute(
                    text(
                        "UPDATE roles SET name = :name, description = :description, "
                        "data_scope = :data_scope, level = :level, built_in = 1, "
                        "updated_at = :updated_at WHERE id = :id"
                    ),
                    {
                        "name": role.name,
                        "description": role.description,
                        "data_scope": role.data_scope,
                        "level": role.level,
                        "updated_at": timestamp,
                        "id": existing,
                    },
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO roles (code, name, description, data_scope, level, "
                        "built_in, status, created_at, updated_at) "
                        "VALUES (:code, :name, :description, :data_scope, :level, 1, 1, "
                        ":created_at, :updated_at)"
                    ),
                    {
                        "code": role.code,
                        "name": role.name,
                        "description": role.description,
                        "data_scope": role.data_scope,
                        "level": role.level,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )

        # 2. Upsert built-in permissions.
        for permission in BUILTIN_PERMISSIONS:
            existing = connection.execute(
                text("SELECT id FROM permissions WHERE code = :code"),
                {"code": permission.code},
            ).scalar()
            if existing:
                connection.execute(
                    text(
                        "UPDATE permissions SET name = :name, description = '', "
                        "module = :module, built_in = 1, updated_at = :updated_at WHERE id = :id"
                    ),
                    {
                        "name": permission.name,
                        "module": permission.module,
                        "updated_at": timestamp,
                        "id": existing,
                    },
                )
            else:
                connection.execute(
                    text(
                        "INSERT INTO permissions (code, name, description, module, built_in, "
                        "status, created_at, updated_at) "
                        "VALUES (:code, :name, '', :module, 1, 1, :created_at, :updated_at)"
                    ),
                    {
                        "code": permission.code,
                        "name": permission.name,
                        "module": permission.module,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )

        # 3. Link roles to their permissions according to the matrix.
        for role_code, permission_codes in get_builtin_role_permissions():
            role_id = connection.execute(
                text("SELECT id FROM roles WHERE code = :code AND built_in = 1"),
                {"code": role_code},
            ).scalar()
            if role_id is None:
                continue
            connection.execute(
                text("DELETE FROM role_permissions WHERE role_id = :role_id"),
                {"role_id": role_id},
            )
            for permission_code in permission_codes:
                permission_id = connection.execute(
                    text("SELECT id FROM permissions WHERE code = :code AND built_in = 1"),
                    {"code": permission_code},
                ).scalar()
                if permission_id is None:
                    continue
                connection.execute(
                    text(
                        "INSERT INTO role_permissions (role_id, permission_id, created_at) "
                        "VALUES (:role_id, :permission_id, :created_at)"
                    ),
                    {
                        "role_id": role_id,
                        "permission_id": permission_id,
                        "created_at": timestamp,
                    },
                )

        # 4. Create one development account per built-in role.
        for username, role_code, display_name in TEST_USERS:
            user_id = connection.execute(
                text("SELECT id FROM users WHERE username = :username"),
                {"username": username},
            ).scalar()
            if user_id is None:
                user_id = connection.execute(
                    text(
                        "INSERT INTO users (username, password_hash, display_name, status, "
                        "created_at, updated_at) VALUES (:username, :password_hash, "
                        ":display_name, 1, :created_at, :updated_at)"
                    ),
                    {
                        "username": username,
                        "password_hash": password_hash,
                        "display_name": display_name,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                ).lastrowid
            assigned = connection.execute(
                text(
                    "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                    "WHERE ur.user_id = :user_id AND r.code = :role_code"
                ),
                {"user_id": user_id, "role_code": role_code},
            ).scalar()
            if not assigned:
                connection.execute(
                    text(
                        "INSERT INTO user_roles (user_id, role_id, created_at) "
                        "SELECT :user_id, id, :created_at FROM roles WHERE code = :role_code"
                    ),
                    {
                        "user_id": user_id,
                        "created_at": timestamp,
                        "role_code": role_code,
                    },
                )

        # 5. Deterministic home campus for non-admin accounts.
        default_campus = connection.execute(
            text("SELECT id FROM campuses WHERE code = 'DEFAULT' LIMIT 1")
        ).scalar()
        if default_campus is None:
            default_campus = connection.execute(
                text(
                    "INSERT INTO campuses(code, name, address, contact_name, contact_mobile, "
                    "status, created_at, updated_at) "
                    "VALUES('DEFAULT','默认校区','','','',1,:created_at,:updated_at)"
                ),
                {"created_at": timestamp, "updated_at": timestamp},
            ).lastrowid
        members = connection.execute(
            text(
                "SELECT DISTINCT u.id, r.code FROM users u "
                "JOIN user_roles ur ON ur.user_id = u.id "
                "JOIN roles r ON r.id = ur.role_id AND r.status = 1 "
                "WHERE u.status = 1 AND r.code IN "
                "('principal','homeroom_teacher','student')"
            )
        ).fetchall()
        for user_id, member_type in members:
            exists = connection.execute(
                text(
                    "SELECT COUNT(*) FROM campus_members "
                    "WHERE campus_id = :campus_id AND user_id = :user_id AND status = 1"
                ),
                {"campus_id": default_campus, "user_id": user_id},
            ).scalar()
            if not exists:
                connection.execute(
                    text(
                        "INSERT INTO campus_members(campus_id, user_id, member_type, is_primary, "
                        "status, joined_at, created_at) VALUES(:campus_id, :user_id, :member_type, "
                        "1, 1, :joined_at, :created_at)"
                    ),
                    {
                        "campus_id": default_campus,
                        "user_id": user_id,
                        "member_type": member_type,
                        "joined_at": timestamp,
                        "created_at": timestamp,
                    },
                )


def bootstrap() -> list[str]:
    """Ensures the database exists, runs migrations, and seeds RBAC data."""
    from .db import ensure_database_exists, get_engine, run_migrations

    from .config import get_settings

    ensure_database_exists(get_settings().database_url)
    engine = get_engine()
    applied = run_migrations(engine)
    seed_rbac()
    return applied
