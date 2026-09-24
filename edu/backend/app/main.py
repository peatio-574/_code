"""FastAPI 应用入口。

职责：注册业务路由、统一异常与响应、CORS，以及所有 `/api/admin/*` 的
统一鉴权中间件（登录 + 写操作 CSRF + 权限码）。启动时自动建库、执行
迁移对账并写入 RBAC 种子。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from .admin_guard import admin_permissions, is_write
from .api import announcements as announcements_api
from .api import auth as auth_api
from .api import campuses as campuses_api
from .api import courses as courses_api
from .api import dashboard as dashboard_api
from .api import dictionaries as dictionaries_api
from .api import exams as exams_api
from .api import files as files_api
from .api import learning as learning_api
from .api import questions as questions_api
from .api import rbac as rbac_api
from .api import reporting as reporting_api
from .api import system_config as system_config_api
from .api import teachers as teachers_api
from .api import users as users_api
from .config import get_settings
from .db import get_engine
from .error import ApiError
from .response import envelope, error_response
from .security import SESSION_COOKIE, authenticate, require_csrf

logger = logging.getLogger("education")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .seed import bootstrap

    applied = bootstrap()
    if applied:
        logger.info("applied migrations: %s", ", ".join(applied))
    logger.info("RBAC seed data initialized")
    yield


app = FastAPI(title="Education API", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-XSRF-Token"],
)


@app.exception_handler(ApiError)
async def handle_api_error(_request: Request, exc: ApiError):
    return error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_request: Request, exc: RequestValidationError):
    return error_response(422, "validation_error", str(exc.errors()))


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return error_response(404, "route_not_found", "Route not found")
    if exc.status_code == 405:
        return error_response(405, "method_not_allowed", "Method not allowed")
    return error_response(exc.status_code, "http_error", str(exc.detail))


@app.middleware("http")
async def disable_api_caching(request: Request, call_next):
    """禁止浏览器缓存接口数据。

    接口返回的是配置/状态等实时数据，若被浏览器缓存，启用或禁用某项后前端仍会
    读取旧值（例如首页背景、友情链接）。图片与视频等静态媒体仍可缓存。
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(("/api/image/", "/api/video/")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def authorize_admin_request(request: Request, call_next):
    """Security boundary for every `/api/admin/*` endpoint."""
    path = request.url.path
    if not path.startswith("/api/admin/"):
        return await call_next(request)

    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return error_response(401, "unauthorized", "authentication required")
    with get_engine().begin() as connection:
        session, _ = authenticate(connection, raw)
        if is_write(request.method):
            require_csrf(request, session.csrf_token)
        permissions = admin_permissions(path, request.method)
        placeholders = ",".join(f":p{i}" for i in range(len(permissions)))
        params = {f"p{i}": code for i, code in enumerate(permissions)}
        params["user_id"] = session.user_id
        found = connection.execute(
            text(
                "SELECT COUNT(*) FROM user_roles ur "
                "JOIN roles r ON r.id = ur.role_id AND r.status = 1 "
                "JOIN role_permissions rp ON rp.role_id = r.id "
                "JOIN permissions p ON p.id = rp.permission_id AND p.status = 1 "
                f"WHERE ur.user_id = :user_id AND p.code IN ({placeholders})"
            ),
            params,
        ).scalar()
    if not found:
        return error_response(403, "forbidden", "permission denied")
    return await call_next(request)


# 认证与个人中心
app.include_router(auth_api.router)
# RBAC
app.include_router(rbac_api.router)
# 组织
app.include_router(campuses_api.router)
app.include_router(users_api.router)
app.include_router(teachers_api.router)
# 内容
app.include_router(courses_api.router)
app.include_router(courses_api.admin_router)
app.include_router(dictionaries_api.router)
app.include_router(dictionaries_api.public_router)
app.include_router(announcements_api.router)
app.include_router(announcements_api.public_router)
app.include_router(system_config_api.router)
app.include_router(system_config_api.public_router)
# 学习
app.include_router(learning_api.router)
# 题库
app.include_router(questions_api.router)
app.include_router(questions_api.admin_router)
# 考试
app.include_router(exams_api.router)
app.include_router(exams_api.admin_router)
# 文件
app.include_router(files_api.router)
# 看板与报表
app.include_router(dashboard_api.router)
app.include_router(reporting_api.router)


@app.get("/api/health")
def health():
    return envelope({"status": "ok"})


@app.get("/api/health/ready")
def readiness():
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
    return envelope({"status": "ready"})


@app.get("/api/status")
def status():
    with get_engine().connect() as connection:
        rows = connection.execute(
            text(
                "SELECT `key`, value FROM sys_config WHERE `key` IN "
                "('system_name', 'logo', 'footer_html')"
            )
        ).fetchall()
    data = {"password_login_enabled": True}
    data.update({row[0]: row[1] for row in rows})
    return envelope(data)
