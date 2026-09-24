"""认证与会话安全。

覆盖：密码哈希（Argon2id，兼容 bcrypt 校验）、会话令牌（仅存 sha256）、
CSRF 校验（常量时间比较）、用户身份加载与 session_epoch 失效。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from bcrypt import checkpw
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .config import Settings
from .error import forbidden, unauthorized

# 会话 Cookie（HttpOnly）与 CSRF Cookie（前端可读）
SESSION_COOKIE = "edu_session"
CSRF_COOKIE = "XSRF-TOKEN"

_hasher = PasswordHasher()


def now() -> int:
    """当前 Unix 秒。"""
    return int(time.time())


def hash_password(password: str) -> str:
    """使用 Argon2id 生成密码哈希。"""
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码：$argon2 走 Argon2，$2 走 bcrypt（兼容历史账号）。"""
    if stored_hash.startswith("$argon2"):
        try:
            return _hasher.verify(stored_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False
    if stored_hash.startswith("$2"):
        try:
            return checkpw(password.encode(), stored_hash.encode())
        except ValueError:
            return False
    return False


def random_token() -> str:
    """生成 32 字节 URL-safe 随机令牌。"""
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    """sha256 十六进制摘要，用于令牌与限流键存储。"""
    return hashlib.sha256(value.encode()).hexdigest()


def require_csrf(request: Request, expected: str) -> None:
    """校验写请求头中的 CSRF 令牌，使用常量时间比较防时序攻击。"""
    supplied = request.headers.get("x-csrf-token") or request.headers.get("x-xsrf-token") or ""
    if not hmac.compare_digest(supplied, expected):
        raise forbidden()


@dataclass
class SessionRow:
    """会话行。"""

    token_hash: str
    user_id: int
    session_epoch: int
    csrf_token: str
    login_log_id: int | None
    expires_at: int


@dataclass
class UserRow:
    """用户行。"""

    id: int
    username: str
    password_hash: str
    display_name: str
    avatar: str
    status: int
    session_epoch: int
    mobile: str | None = None


@dataclass
class Actor:
    """已认证的会话与用户。"""

    session: SessionRow
    user: UserRow


def _session_cookie_kwargs(settings: Settings) -> dict:
    """会话/CSRF Cookie 的公共属性。"""
    return {
        "path": "/",
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "max_age": settings.session_max_age_seconds,
    }


def set_auth_cookies(response, raw_token: str, csrf_token: str, settings: Settings) -> None:
    """登录成功后写入会话 Cookie 与 CSRF Cookie。"""
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        httponly=True,
        **_session_cookie_kwargs(settings),
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        **_session_cookie_kwargs(settings),
    )


def clear_auth_cookies(response, settings: Settings) -> None:
    """退出登录时清除两个 Cookie。"""
    response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure, samesite="lax")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=settings.cookie_secure, samesite="lax")


def authenticate(connection: Connection, raw_token: str | None) -> tuple[SessionRow, UserRow]:
    """校验会话令牌并返回会话与用户；无效会话会被删除。"""
    if not raw_token:
        raise unauthorized()
    token_hash = digest(raw_token)
    session_row = connection.execute(
        text(
            "SELECT token_hash, user_id, session_epoch, csrf_token, login_log_id, expires_at "
            "FROM auth_sessions WHERE token_hash = :token_hash"
        ),
        {"token_hash": token_hash},
    ).mappings().first()
    if session_row is None:
        raise unauthorized()
    session = SessionRow(**session_row)
    user_row = connection.execute(
        text(
            "SELECT id, username, password_hash, display_name, avatar, status, session_epoch, "
            "mobile FROM users WHERE id = :id"
        ),
        {"id": session.user_id},
    ).mappings().first()
    user = UserRow(**user_row) if user_row is not None else None
    valid = (
        user is not None
        and user.status == 1
        and user.session_epoch == session.session_epoch
        and session.expires_at > now()
    )
    if not valid:
        connection.execute(
            text("DELETE FROM auth_sessions WHERE token_hash = :token_hash"),
            {"token_hash": token_hash},
        )
        raise unauthorized()
    return session, user  # type: ignore[return-value]


def get_actor(request: Request) -> Actor:
    """FastAPI dependency: authenticates the cookie session on its own connection."""
    from .db import get_engine

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise unauthorized()
    with get_engine().connect() as connection:
        session, user = authenticate(connection, raw)
        connection.commit()
    return Actor(session=session, user=user)


def load_user_data(user: UserRow, connection: Connection, csrf_token: str | None) -> dict:
    """组装前端所需的用户信息：角色、权限、数据范围、CSRF。"""
    # 角色按内置优先级排序（超管在前）
    roles = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.code FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :id AND r.status = 1 "
                "ORDER BY CASE r.code WHEN 'system_admin' THEN 0 WHEN 'principal' THEN 1 "
                "WHEN 'homeroom_teacher' THEN 2 ELSE 3 END"
            ),
            {"id": user.id},
        ).fetchall()
    ]
    # 所有启用角色的有效权限并集
    permissions = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT DISTINCT p.code FROM permissions p "
                "JOIN role_permissions rp ON rp.permission_id = p.id "
                "JOIN user_roles ur ON ur.role_id = rp.role_id "
                "JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id AND p.status = 1 AND r.status = 1 ORDER BY p.code"
            ),
            {"id": user.id},
        ).fetchall()
    ]
    # 数据范围取所有角色中的最大值
    scopes = [
        row[0]
        for row in connection.execute(
            text(
                "SELECT r.data_scope FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
                "WHERE ur.user_id = :id AND r.status = 1"
            ),
            {"id": user.id},
        ).fetchall()
    ]
    data_scope = next((s for s in ("all", "tree", "direct", "self") if s in scopes), "self")
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "avatar": user.avatar,
        "mobile": user.mobile or "",
        "role": roles[0] if roles else "",
        "roles": roles,
        "permissions": permissions,
        "data_scope": data_scope,
        "csrf_token": csrf_token,
    }


def bump_session_epoch(connection: Connection, user_id: int) -> None:
    """递增 session_epoch，使该用户所有旧会话立即失效。"""
    connection.execute(
        text("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = :id"),
        {"id": user_id},
    )


def build_dummy_hash() -> str:
    """生成一个假的密码哈希，用于用户不存在时保持恒定校验耗时。"""
    return hash_password(random_token())
