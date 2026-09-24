"""控制台路由权限映射。

所有 `/api/admin/*` 请求由中间件统一鉴权：登录校验 + 写操作 CSRF 校验 +
按资源映射所需权限码。未知资源默认要求 console.system.manage（安全兜底）。
"""
from __future__ import annotations

from .domain.rbac import (
    PERM_ADMINISTRATORS_MANAGE,
    PERM_ANNOUNCEMENTS_MANAGE,
    PERM_CAMPUS_MEMBERS_MANAGE,
    PERM_CAMPUSES_MANAGE,
    PERM_CAMPUSES_VIEW,
    PERM_COURSES_MANAGE,
    PERM_DICTIONARIES_MANAGE,
    PERM_DASHBOARD_VIEW,
    PERM_ROLES_MANAGE,
    PERM_EXAMS_COMPOSE,
    PERM_EXAMS_EDIT,
    PERM_EXAMS_MANAGE,
    PERM_EXAMS_PUBLISH,
    PERM_EXAMS_VIEW,
    PERM_EXAMS_WITHDRAW,
    PERM_QUESTIONS_MANAGE,
    PERM_STUDENTS_MANAGE,
    PERM_SYSTEM_MANAGE,
    PERM_TEACHERS_MANAGE,
)

_GET_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_write(method: str) -> bool:
    """非 GET/HEAD/OPTIONS 视为写操作，需要 CSRF 校验。"""
    return method.upper() not in _GET_METHODS


def admin_permissions(path: str, method: str) -> list[str]:
    """根据请求路径与方法返回所需权限码集合（命中其一即通过）。

    映射规则与旧 Rust 后端 admin_permissions 保持一致。
    """
    resource = path.removeprefix("/api/admin/").split("/", 1)[0]
    upper = method.upper()
    if resource == "dashboard":
        return [PERM_DASHBOARD_VIEW]
    if resource in ("roles", "role"):
        return [PERM_ROLES_MANAGE]
    if resource in ("announcement", "announcements"):
        return [PERM_ANNOUNCEMENTS_MANAGE]
    if resource in ("course", "courses"):
        return [PERM_COURSES_MANAGE]
    if resource == "questions" and path.endswith("/options") and upper == "GET":
        return [PERM_QUESTIONS_MANAGE, PERM_EXAMS_COMPOSE, PERM_EXAMS_EDIT]
    if resource in ("question", "questions", "question-category", "question-categories"):
        return [PERM_QUESTIONS_MANAGE]
    if resource in ("exam", "exams"):
        if path.endswith("/publish"):
            return [PERM_EXAMS_PUBLISH]
        if path.endswith("/withdraw"):
            return [PERM_EXAMS_WITHDRAW]
        if upper == "GET":
            return [PERM_EXAMS_VIEW, PERM_EXAMS_MANAGE]
        if upper == "POST" and path.endswith("/exam"):
            return [PERM_EXAMS_COMPOSE, PERM_EXAMS_MANAGE]
        if upper in ("PUT", "DELETE"):
            return [PERM_EXAMS_EDIT, PERM_EXAMS_MANAGE]
        return [PERM_EXAMS_MANAGE]
    if resource in ("user", "users", "user-hierarchy"):
        return [PERM_ADMINISTRATORS_MANAGE, PERM_STUDENTS_MANAGE]
    if resource == "campuses":
        if "/members" in path:
            if upper == "GET":
                return [PERM_CAMPUS_MEMBERS_MANAGE, PERM_CAMPUSES_VIEW]
            return [PERM_CAMPUS_MEMBERS_MANAGE]
        if upper == "GET":
            return [PERM_CAMPUSES_VIEW, PERM_CAMPUSES_MANAGE]
        return [PERM_CAMPUSES_MANAGE]
    if resource in ("students", "student", "learning-records", "statistics", "exports"):
        return [PERM_STUDENTS_MANAGE]
    if resource == "exam-attempts":
        return [PERM_EXAMS_VIEW, PERM_EXAMS_MANAGE]
    if resource in ("teacher", "teachers"):
        return [PERM_TEACHERS_MANAGE]
    if resource in ("dictionary-types", "dictionary-items"):
        return [PERM_DICTIONARIES_MANAGE]
    if resource in ("home-banners", "system", "rbac"):
        return [PERM_SYSTEM_MANAGE]
    # Secure-by-default for newly added admin resources.
    return [PERM_SYSTEM_MANAGE]
