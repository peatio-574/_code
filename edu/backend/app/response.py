from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi.responses import JSONResponse


def _default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


class SafeJSONResponse(JSONResponse):
    """JSONResponse that tolerates Decimal and other non-native types."""

    def render(self, content: Any) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=_default,
        ).encode("utf-8")


def envelope(data: Any = None, *, success: bool = True, code: str = "0000", message: str = "") -> dict:
    """Standard business response envelope used by every API handler."""
    return {"success": success, "code": code, "message": message, "data": data}


def ok(data: Any = None) -> JSONResponse:
    return SafeJSONResponse(status_code=200, content=envelope(data))


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return SafeJSONResponse(
        status_code=status_code,
        content={"success": False, "code": code, "message": message},
    )
