"""Request-scoped context available to services without threading it through
every function signature.

Populated by `RequestContextMiddleware` (see `app.core.middleware`) at the
start of each request. Services read it when writing audit/security events
so that "who did this, from where" is captured consistently without every
service method needing an `ip_address` / `user_agent` parameter.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4


@dataclass(slots=True)
class RequestContext:
    request_id: str
    ip_address: str | None
    user_agent: str | None


_context_var: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def set_request_context(ip_address: str | None, user_agent: str | None) -> RequestContext:
    ctx = RequestContext(request_id=str(uuid4()), ip_address=ip_address, user_agent=user_agent)
    _context_var.set(ctx)
    return ctx


def get_request_context() -> RequestContext:
    ctx = _context_var.get()
    if ctx is None:
        # Fallback for code paths invoked outside an HTTP request (scripts, tests).
        return RequestContext(request_id=str(uuid4()), ip_address=None, user_agent=None)
    return ctx
