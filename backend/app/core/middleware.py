"""ASGI middleware: request context capture and baseline security headers.

In production, the platform sits behind a CDN/WAF and API gateway (see the
architecture doc). Those are responsible for the heavy-lifting security
controls (WAF rules, DDoS protection, IP allow-listing for admin routes).
This middleware only handles what the application itself is responsible
for: knowing the caller's IP/user-agent for audit purposes, and setting
sane default response headers.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.context import set_request_context

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware:
    """Populates the contextvar-based RequestContext for each request and
    stamps the response with an `X-Request-ID` header for support/debugging.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        client_ip = _resolve_client_ip(request)
        user_agent = request.headers.get("user-agent")
        ctx = set_request_context(ip_address=client_ip, user_agent=user_agent)

        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", ctx.request_id.encode()))
                headers.append((b"x-content-type-options", b"nosniff"))
                headers.append((b"x-frame-options", b"DENY"))
                headers.append((b"referrer-policy", b"no-referrer"))
            await send(message)

        await self.app(scope, receive, send_wrapper)
        _ = time.perf_counter() - start  # hook point for latency metrics/logging


def _resolve_client_ip(request: Request) -> str | None:
    """Resolve the originating client IP.

    Trusts `X-Forwarded-For` only because, in deployment, the application
    sits behind the platform's own API gateway/load balancer which sets
    this header itself (see architecture: CDN -> WAF -> Gateway -> app).
    Direct-to-app deployments (e.g. local `docker compose up`) fall back to
    the raw peer address.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def new_request_id() -> str:
    return str(uuid.uuid4())
