"""Shared, framework-agnostic application error types.

Module-specific error codes (e.g. Identity's `EMAIL_ALREADY_REGISTERED`)
live in that module's `domain/exceptions.py` and subclass `AppError`.
Keeping the base here means every future module (Onboarding, Pharmacy, ...)
raises errors that the same global exception handler in `app.main` can
render consistently.
"""

from __future__ import annotations


class ErrorField:
    """A single field-level validation error."""

    __slots__ = ("field", "message")

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "message": self.message}


class AppError(Exception):
    """Base class for all domain/application errors.

    `status_code` defaults to 400 and should be overridden per error code
    (see each module's exception subclass for the canonical mapping).
    """

    status_code: int = 400

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        fields: list[ErrorField] | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.fields = fields or []
        # `details` is a free-form structured payload for errors that need
        # more than per-field messages — e.g. Onboarding's
        # ONBOARDING_APPLICATION_INCOMPLETE, which reports
        # {missingDocuments: [...], incompleteSections: [...]} (spec
        # section 31). `fields` stays the mechanism for simple per-field
        # validation messages (Identity's usage); the two are independent
        # and either/both may be set.
        self.details = details
        if status_code is not None:
            self.status_code = status_code


class ValidationAppError(AppError):
    status_code = 422

    def __init__(self, fields: list[ErrorField]) -> None:
        super().__init__(
            code="VALIDATION_ERROR",
            message="The submitted information is invalid.",
            fields=fields,
        )


class NotFoundError(AppError):
    status_code = 404

    def __init__(self, message: str = "The requested resource was not found.") -> None:
        super().__init__(code="NOT_FOUND", message=message)


class PermissionDeniedError(AppError):
    status_code = 403

    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(code="PERMISSION_DENIED", message=message)


class UnauthorizedError(AppError):
    status_code = 401

    def __init__(self, code: str = "UNAUTHORIZED", message: str = "Authentication is required.") -> None:
        super().__init__(code=code, message=message)


class RateLimitedError(AppError):
    status_code = 429

    def __init__(self, message: str = "Too many requests. Please try again later.") -> None:
        super().__init__(code="RATE_LIMITED", message=message)


class IdempotencyKeyReusedError(AppError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            code="IDEMPOTENCY_KEY_REUSED",
            message="This idempotency key was already used with a different request body.",
        )
