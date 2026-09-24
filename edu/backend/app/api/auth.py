"""认证与个人中心：登录、登出、当前用户、注册、修改资料与密码。"""

from __future__ import annotations


import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text

from ..config import Settings, get_settings
from ..db import get_engine, named_lock
from ..error import conflict, invalid_credentials, rate_limited, validation
from ..response import ok
from ..security import (
    SESSION_COOKIE,
    UserRow,
    authenticate,
    build_dummy_hash,
    clear_auth_cookies,
    digest,
    hash_password,
    load_user_data,
    now,
    random_token,
    require_csrf,
    set_auth_cookies,
    verify_password,
)

router = APIRouter(prefix="/api")

_dummy_hash: str | None = None


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = build_dummy_hash()
    return _dummy_hash


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: str = ""
    mobile: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


def _optional(value: str) -> str | None:
    value = value.strip()
    return value or None


def _validate_registration(username: str, password: str, email: str | None, mobile: str | None) -> None:
    if not (3 <= len(username) <= 100) or not re.fullmatch(r"[A-Za-z0-9_.\-]+", username):
        raise validation("username must be 3-100 letters, digits, dots, underscores, or hyphens")
    if (
        not (8 <= len(password) <= 128)
        or not any(c.isupper() for c in password)
        or not any(c.islower() for c in password)
        or not any(c.isdigit() for c in password)
        or all(c.isalnum() for c in password)
    ):
        raise validation(
            "password must be 8-128 characters and include upper, lower, digit, and special characters"
        )
    if email is not None:
        parts = email.split("@")
        if len(parts) != 2 or "." not in parts[1]:
            raise validation("email is invalid")
    if mobile is not None and (not (5 <= len(mobile) <= 15) or not mobile.isdigit()):
        raise validation("mobile is invalid")


def _ensure_not_locked(connection, key: str) -> None:
    locked_until = connection.execute(
        text("SELECT locked_until FROM login_throttles WHERE throttle_key = :key"),
        {"key": key},
    ).scalar()
    if locked_until is not None and locked_until > now():
        raise rate_limited()


def _record_failure(
    connection, key: str, identity: str, ip: str, user_agent: str, settings: Settings
) -> None:
    """记录一次登录失败并累加计数；达到阈值时写入锁定时间。"""
    current = connection.execute(
        text("SELECT failure_count, locked_until FROM login_throttles WHERE throttle_key = :key"),
        {"key": key},
    ).first()
    timestamp = now()
    if current is not None and (current[1] is None or current[1] > timestamp):
        count = current[0] + 1
    else:
        count = 1
    locked_until = (
        timestamp + settings.login_lockout_seconds
        if count >= settings.login_max_failures
        else None
    )
    if current is not None:
        connection.execute(
            text(
                "UPDATE login_throttles SET failure_count = :count, locked_until = :locked_until, "
                "updated_at = :updated_at WHERE throttle_key = :key"
            ),
            {"count": count, "locked_until": locked_until, "updated_at": timestamp, "key": key},
        )
    else:
        connection.execute(
            text(
                "INSERT INTO login_throttles(throttle_key, failure_count, locked_until, updated_at) "
                "VALUES(:key, :count, :locked_until, :updated_at)"
            ),
            {"key": key, "count": count, "locked_until": locked_until, "updated_at": timestamp},
        )
    connection.execute(
        text(
            "INSERT INTO login_logs(attempted_identity, success, failure_reason, client_ip, "
            "user_agent, login_at) VALUES(:identity, 0, 'invalid_credentials', :ip, :ua, :login_at)"
        ),
        {"identity": identity, "ip": ip, "ua": user_agent, "login_at": timestamp},
    )


@router.post("/register")
def register(payload: RegisterRequest):
    """注册学员账号：校验参数，唯一性在命名锁内检查并原子分配 student 角色。"""
    username = payload.username.strip()
    email = _optional(payload.email)
    mobile = _optional(payload.mobile)
    _validate_registration(username, payload.password, email, mobile)
    password_hash = hash_password(payload.password)
    timestamp = now()
    with named_lock("users:identity") as connection:
        exists = connection.execute(
            text(
                "SELECT COUNT(*) FROM users WHERE username = :username "
                "OR (:email IS NOT NULL AND email = :email) "
                "OR (:mobile IS NOT NULL AND mobile = :mobile)"
            ),
            {"username": username, "email": email, "mobile": mobile},
        ).scalar()
        if exists:
            raise conflict("username, email, or mobile already exists")
        connection.execute(
            text(
                "INSERT INTO users(username, password_hash, display_name, email, mobile, "
                "created_at, updated_at) VALUES(:username, :hash, :display_name, :email, "
                ":mobile, :created_at, :updated_at)"
            ),
            {
                "username": username,
                "hash": password_hash,
                "display_name": payload.display_name.strip(),
                "email": email,
                "mobile": mobile,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
        user_id = connection.execute(
            text("SELECT id FROM users WHERE username = :username"), {"username": username}
        ).scalar()
        connection.execute(
            text(
                "INSERT INTO user_roles(user_id, role_id, created_at) "
                "SELECT :user_id, id, :created_at FROM roles WHERE code = 'student'"
            ),
            {"user_id": user_id, "created_at": timestamp},
        )
    return ok({"username": username, "userId": user_id})


@router.post("/login")
def login(payload: LoginRequest, request: Request, settings: Settings = Depends(get_settings)):
    """登录入口。

    支持用户名/邮箱/手机号；同一「IP+账号」连续失败达阈值后锁定。
    成功时清零计数、必要时升级密码哈希，并写入会话与登录日志。
    """
    identity = payload.username.strip().lower()
    if not identity or not payload.password:
        raise validation("username and password are required")
    client_ip = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:512]
    throttle_key = digest(f"{client_ip}|{identity}")

    with named_lock(f"login_throttle:{throttle_key}") as connection:
        _ensure_not_locked(connection, throttle_key)
        user = connection.execute(
            text(
                "SELECT id, username, password_hash, display_name, avatar, status, session_epoch "
                "FROM users WHERE username = :identity OR email = :identity OR mobile = :identity LIMIT 1"
            ),
            {"identity": identity},
        ).mappings().first()
        valid = False
        if user is not None and user["status"] == 1:
            valid = verify_password(payload.password, user["password_hash"])
        else:
            # 用户不存在时也执行一次校验，保持恒定耗时防时序侧信道
            verify_password(payload.password, _dummy())
        if not valid or user is None:
            _record_failure(connection, throttle_key, identity, client_ip, user_agent, settings)
            raise invalid_credentials()
        # 登录成功：清零失败计数
        connection.execute(
            text("DELETE FROM login_throttles WHERE throttle_key = :key"), {"key": throttle_key}
        )
        # 历史 bcrypt 密码自动升级为 Argon2，并递增 session_epoch 使旧会话失效
        if not user["password_hash"].startswith("$argon2"):
            upgraded = hash_password(payload.password)
            connection.execute(
                text(
                    "UPDATE users SET password_hash = :hash, updated_at = :updated_at, "
                    "session_epoch = session_epoch + 1 WHERE id = :id"
                ),
                {"hash": upgraded, "updated_at": now(), "id": user["id"]},
            )
            user = dict(user)
            user["session_epoch"] += 1
        timestamp = now()
        raw_token = random_token()
        csrf_token = random_token()
        token_hash = digest(raw_token)
        log_id = connection.execute(
            text(
                "INSERT INTO login_logs(user_id, attempted_identity, success, client_ip, "
                "user_agent, login_at) VALUES(:user_id, :identity, 1, :ip, :ua, :login_at)"
            ),
            {
                "user_id": user["id"],
                "identity": identity,
                "ip": client_ip,
                "ua": user_agent,
                "login_at": timestamp,
            },
        ).lastrowid
        connection.execute(
            text(
                "INSERT INTO auth_sessions(token_hash, user_id, session_epoch, csrf_token, "
                "login_log_id, created_at, last_seen_at, expires_at, client_ip, user_agent) "
                "VALUES(:token_hash, :user_id, :session_epoch, :csrf_token, :login_log_id, "
                ":created_at, :last_seen_at, :expires_at, :client_ip, :user_agent)"
            ),
            {
                "token_hash": token_hash,
                "user_id": user["id"],
                "session_epoch": user["session_epoch"],
                "csrf_token": csrf_token,
                "login_log_id": log_id,
                "created_at": timestamp,
                "last_seen_at": timestamp,
                "expires_at": timestamp + settings.session_max_age_seconds,
                "client_ip": client_ip,
                "user_agent": user_agent,
            },
        )
        data = load_user_data(UserRow(**user), connection, csrf_token)

    response = ok(data)
    set_auth_cookies(response, raw_token, csrf_token, settings)
    return response


@router.get("/user/me")
@router.get("/user/self")
def current_user(request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    with get_engine().begin() as connection:
        session, user = authenticate(connection, raw)
        connection.execute(
            text("UPDATE auth_sessions SET last_seen_at = :ts WHERE token_hash = :token_hash"),
            {"ts": now(), "token_hash": session.token_hash},
        )
        return ok(load_user_data(user, connection, None))


@router.post("/logout")
@router.get("/logout")
def logout(request: Request, settings: Settings = Depends(get_settings)):
    raw = request.cookies.get(SESSION_COOKIE)
    with get_engine().begin() as connection:
        session, _ = authenticate(connection, raw)
        require_csrf(request, session.csrf_token)
        connection.execute(
            text("DELETE FROM auth_sessions WHERE token_hash = :token_hash"),
            {"token_hash": session.token_hash},
        )
        if session.login_log_id is not None:
            connection.execute(
                text("UPDATE login_logs SET logout_at = :ts WHERE id = :id"),
                {"ts": now(), "id": session.login_log_id},
            )
    response = ok({})
    clear_auth_cookies(response, settings)
    return response


class ProfileRequest(BaseModel):
    display_name: str | None = None
    mobile: str | None = None
    avatar: str | None = None


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    confirm_password: str


@router.put("/user/profile")
def update_profile(payload: ProfileRequest, request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    with named_lock(f"user:profile") as connection:
        session, user = authenticate(connection, raw)
        require_csrf(request, session.csrf_token)
        current = connection.execute(
            text("SELECT username, mobile FROM users WHERE id = :id"), {"id": user.id}
        ).mappings().first()
        mobile = payload.mobile.strip() if payload.mobile is not None else None
        if mobile is not None:
            if mobile and (not (5 <= len(mobile) <= 15) or not mobile.isdigit()):
                raise validation("手机号格式不正确")
            if mobile and mobile != (current["mobile"] or ""):
                exists = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM users WHERE (mobile = :mobile OR username = :mobile) "
                        "AND id <> :id"
                    ),
                    {"mobile": mobile, "id": user.id},
                ).scalar()
                if exists:
                    raise conflict("该手机号已被其他账号使用")
        fields = ["updated_at = :updated_at"]
        params: dict = {"updated_at": now(), "id": user.id}
        if payload.display_name is not None:
            fields.append("display_name = :display_name")
            params["display_name"] = payload.display_name.strip()
        if payload.avatar is not None:
            fields.append("avatar = :avatar")
            params["avatar"] = payload.avatar.strip()
        if mobile is not None:
            fields.append("mobile = :mobile")
            params["mobile"] = mobile or None
            # 学员手机号即登录账号，需同步更新
            if payload.mobile and current["username"] == (current["mobile"] or ""):
                fields.append("username = :username")
                params["username"] = mobile
        connection.execute(
            text(f"UPDATE users SET {', '.join(fields)} WHERE id = :id"), params
        )
    return ok({"id": user.id})


@router.post("/user/change-password")
def change_password(payload: ChangePasswordRequest, request: Request):
    raw = request.cookies.get(SESSION_COOKIE)
    with named_lock("user:password") as connection:
        session, user = authenticate(connection, raw)
        require_csrf(request, session.csrf_token)
        if not verify_password(payload.old_password, user.password_hash):
            raise validation("原密码错误")
        if payload.new_password != payload.confirm_password:
            raise validation("两次输入的密码不一致")
        if len(payload.new_password) < 6:
            raise validation("密码长度不能少于6位")
        connection.execute(
            text(
                "UPDATE users SET password_hash = :hash, updated_at = :updated_at, "
                "session_epoch = session_epoch + 1 WHERE id = :id"
            ),
            {"hash": hash_password(payload.new_password), "updated_at": now(), "id": user.id},
        )
    return ok({"id": user.id})
