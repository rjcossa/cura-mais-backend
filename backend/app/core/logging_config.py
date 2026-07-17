"""Logging configuration.

Per spec section 23.2, the application must never log passwords, raw
tokens, OTPs, MFA secrets, or recovery codes. The codebase enforces this by
convention (services log identifiers/hashes, never raw secret values —
see `app/modules/identity/application/security.py` for the only place raw
secrets are handled), and this module adds a belt-and-braces filter that
redacts common secret-shaped fields if they ever end up in `extra=`.
"""

from __future__ import annotations

import logging
import sys

from app.core.config import get_settings

_REDACTED_KEYS = {
    "password",
    "new_password",
    "current_password",
    "access_token",
    "refresh_token",
    "token",
    "otp",
    "code",
    "secret",
    "recovery_code",
}


class RedactSensitiveFieldsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key in _REDACTED_KEYS:
            if hasattr(record, key):
                setattr(record, key, "***REDACTED***")
        return True


def configure_logging() -> None:
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactSensitiveFieldsFilter())

    if settings.log_json:
        from pythonjsonlogger.json import JsonFormatter

        formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s"
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )

    handler.setFormatter(formatter)
    root.handlers = [handler]

    # Quiet noisy third-party loggers at INFO in dev.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )
