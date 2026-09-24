"""业务异常与统一错误码。

每个错误携带 HTTP 状态码与稳定的机器可读 code，由全局异常处理器
统一渲染为 {success:false, code, message}，与旧后端保持兼容。
"""
from __future__ import annotations


class ApiError(Exception):
    """业务异常：HTTP 状态码 + 错误码 + 可读信息。"""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def unauthorized() -> ApiError:
    """未登录或会话失效。"""
    return ApiError(401, "unauthorized", "authentication required")


def invalid_credentials() -> ApiError:
    """用户名或密码错误。"""
    return ApiError(401, "login_failed", "invalid username or password")


def forbidden() -> ApiError:
    """权限不足（含越权访问其他校区）。"""
    return ApiError(403, "forbidden", "permission denied")


def validation(message: str) -> ApiError:
    """参数或业务校验失败。"""
    return ApiError(422, "validation_error", message)


def bad_request(message: str) -> ApiError:
    """请求格式错误。"""
    return ApiError(400, "bad_request", message)


def conflict(message: str) -> ApiError:
    """与现有数据冲突（重复、被引用、状态不允许）。"""
    return ApiError(409, "conflict", message)


def not_found(message: str) -> ApiError:
    """对象不存在。"""
    return ApiError(404, "not_found", message)


def rate_limited() -> ApiError:
    """登录失败次数过多，稍后重试。"""
    return ApiError(429, "login_rate_limited", "too many login attempts")


def internal() -> ApiError:
    """服务器内部错误。"""
    return ApiError(500, "internal_error", "internal server error")
