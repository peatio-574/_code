"""通用工具：时间、分页、脱敏、校区归属与当前操作者。

供各业务 handler 复用的轻量函数集合。
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Connection


def now() -> int:
    """当前 Unix 秒（全库审计时间统一由此生成）。"""
    return int(time.time())


def page_params(request: Request) -> tuple[int, int]:
    """解析分页参数：页码 p（默认1，最小1），每页 page_size 仅允许 20/50/100。"""
    page = max(1, int(request.query_params.get("p", 1) or 1))
    try:
        size = int(request.query_params.get("page_size", 20) or 20)
    except ValueError:
        size = 20
    if size not in (20, 50, 100):
        size = 20
    return page, size


def mask_phone(phone: str | None) -> str:
    """手机号脱敏：138****0000。"""
    if not phone or len(phone) < 7:
        return phone or ""
    return f"{phone[:3]}****{phone[-4:]}"


def page_result(items: list[Any], total: int, page: int, size: int) -> dict:
    """统一分页响应结构。"""
    return {"items": items, "total": total, "page": page, "page_size": size}


def object_campus_ok(
    connection: Connection,
    campus_id: int | None,
    actor_campus_id: int | None,
    is_super: bool,
) -> bool:
    """对象级校区校验：超管放行，其余要求对象校区等于操作者校区。"""
    if is_super:
        return True
    return campus_id == actor_campus_id


def actor_primary_campus(connection: Connection, user_id: int) -> int | None:
    """取用户的主校区 ID（campus_members 中 is_primary=1 的首条）。"""
    return connection.execute(
        text(
            "SELECT campus_id FROM campus_members "
            "WHERE user_id = :user_id AND status = 1 AND is_primary = 1 ORDER BY id LIMIT 1"
        ),
        {"user_id": user_id},
    ).scalar()


def is_super_admin(connection: Connection, user_id: int) -> bool:
    """判断用户是否拥有启用中的超级管理员角色。"""
    return bool(
        connection.execute(
            text(
                "SELECT COUNT(*) FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :user_id AND r.code = 'system_admin' AND r.status = 1"
            ),
            {"user_id": user_id},
        ).scalar()
    )


def actor_id(request: Request) -> int:
    """从 Cookie 会话解析当前操作者 ID；未登录抛 401。"""
    from .db import get_engine
    from .error import unauthorized
    from .security import SESSION_COOKIE, authenticate

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise unauthorized()
    with get_engine().connect() as connection:
        session, _ = authenticate(connection, raw)
        connection.commit()
    return session.user_id


def actor_session(request: Request):
    """从 Cookie 会话解析会话行与用户行。"""
    from .db import get_engine
    from .error import unauthorized
    from .security import SESSION_COOKIE, authenticate

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise unauthorized()
    with get_engine().connect() as connection:
        session, user = authenticate(connection, raw)
        connection.commit()
    return session, user
