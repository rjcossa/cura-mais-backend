"""FastAPI application entry point for the Health Platform backend
(modular monolith — currently the Identity and Onboarding modules).

Run locally with:

    uvicorn app.main:app --reload

See backend/README.md for full setup instructions.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import dispose_engine, get_engine
from app.core.envelope import error_body
from app.core.exceptions import AppError, ErrorField, ValidationAppError
from app.core.logging_config import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.modules.identity.api.router import identity_router
from app.modules.identity.application.outbox_dispatcher import run_polling_loop as run_identity_outbox_loop
from app.modules.onboarding.api.router import onboarding_router
from app.modules.onboarding.application.outbox_dispatcher import (
    run_polling_loop as run_onboarding_outbox_loop,
)
from app.modules.onboarding.application.scheduled_tasks import (
    run_polling_loop as run_onboarding_scheduled_tasks,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    logger.info("Starting %s (environment=%s)", settings.app_name, settings.environment)

    stop_event = asyncio.Event()
    background_tasks = [
        asyncio.create_task(run_identity_outbox_loop(stop_event=stop_event)),
        asyncio.create_task(run_onboarding_outbox_loop(stop_event=stop_event)),
        asyncio.create_task(run_onboarding_scheduled_tasks(stop_event=stop_event)),
    ]

    yield

    stop_event.set()
    for task in background_tasks:
        task.cancel()
    for task in background_tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    await dispose_engine()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Health Platform & Digital Medicine Marketplace backend (modular monolith). "
            "**Identity**: registration, authentication, sessions, MFA, social login, and "
            "role/permission management. **Onboarding**: applicant onboarding, document "
            "review, verification checks, and maker-checker approval for doctors, "
            "nutritionists, hospitals, clinics, and pharmacies."
        ),
        version="0.2.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Authentication", "description": "Registration, login, token refresh, logout"},
            {"name": "Verification", "description": "Email and mobile verification"},
            {"name": "Password", "description": "Password change, forgot, reset"},
            {"name": "Multi-Factor Authentication", "description": "TOTP enrolment and login challenges"},
            {"name": "Sessions", "description": "Device/session listing and revocation"},
            {"name": "Social Login", "description": "Google / Apple / Facebook sign-in"},
            {"name": "Users", "description": "Current user profile management"},
            {"name": "Back-Office Administration", "description": "Role assignment, suspension, activation"},
            {"name": "Onboarding — Applicant", "description": "Application lifecycle, sections, documents"},
            {"name": "Onboarding — Back Office", "description": "Search, assignment, risk flags, notes"},
            {"name": "Onboarding — Review", "description": "Review lifecycle and document review"},
            {"name": "Onboarding — Decisions", "description": "Verification checks, information requests, approve/reject/suspend"},
            {"name": "System", "description": "Health checks"},
        ],
    )

    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(identity_router, prefix=settings.api_v1_prefix)
    app.include_router(onboarding_router, prefix=settings.api_v1_prefix)

    @app.get("/health", tags=["System"], summary="Liveness check")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["System"], summary="Readiness check (verifies DB connectivity)")
    async def health_ready() -> dict:
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=503, content={"status": "unavailable", "detail": str(exc)})
        return {"status": "ready"}

    return app


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=error_body(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            ErrorField(field=".".join(str(p) for p in err["loc"][1:]) or str(err["loc"][-1]), message=err["msg"])
            for err in exc.errors()
        ]
        return JSONResponse(status_code=422, content=error_body(ValidationAppError(fields)))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception while processing %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
            },
        )


app = create_app()
