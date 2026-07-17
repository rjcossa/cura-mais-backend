"""Standard `{success, data}` / `{success, error}` response envelope.

Every endpoint in the platform returns one of these two shapes, matching
the contract examples in the Identity module specification (section 7.2,
section 27).
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.exceptions import AppError

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[dict[str, str]] | None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    error: ErrorDetail


class SuccessEnvelope(BaseModel, Generic[T]):
    success: bool = True
    data: T


def success(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data}


def error_body(exc: AppError) -> dict[str, Any]:
    body: dict[str, Any] = {
        "success": False,
        "error": {"code": exc.code, "message": exc.message},
    }
    if exc.fields:
        body["error"]["fields"] = [f.to_dict() for f in exc.fields]
    if exc.details:
        body["error"]["details"] = exc.details
    return body
