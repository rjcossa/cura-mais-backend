"""A minimal in-process rate limiter.

This is intentionally dependency-free (no Redis) so the whole backend runs
with nothing but PostgreSQL, which matches the "ready to run locally"
requirement for the MVP. It is correct for a single application process.

**Production note:** once the Identity module runs as more than one
instance/container, this must be swapped for a shared backend (Redis is
the natural choice, per the architecture doc's caching layer) so that
limits are enforced across instances rather than per-process. The
`RateLimiter` interface below is deliberately small so that swap is a
drop-in change — see `InMemoryRateLimiter` for the implementation to
replace.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import RateLimitedError


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    limit: int
    window_seconds: int


# Policy table transcribed from the Identity module spec, section 23.4.
POLICIES: dict[str, RateLimitPolicy] = {
    "login": RateLimitPolicy(limit=5, window_seconds=15 * 60),
    "registration": RateLimitPolicy(limit=5, window_seconds=60 * 60),
    "password_reset_request": RateLimitPolicy(limit=3, window_seconds=60 * 60),
    "email_verification_resend": RateLimitPolicy(limit=3, window_seconds=60 * 60),
    "mobile_otp_send": RateLimitPolicy(limit=3, window_seconds=15 * 60),
    "otp_verification": RateLimitPolicy(limit=5, window_seconds=5 * 60),
    "mfa_verification": RateLimitPolicy(limit=5, window_seconds=5 * 60),
    "refresh_token": RateLimitPolicy(limit=30, window_seconds=60 * 60),
    "social_login": RateLimitPolicy(limit=20, window_seconds=60 * 60),
}


class RateLimiter(Protocol):
    async def enforce(self, operation: str, *identity_parts: str) -> None: ...


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def enforce(self, operation: str, *identity_parts: str) -> None:
        policy = POLICIES.get(operation)
        if policy is None:
            return  # Unthrottled operation.

        key = operation + ":" + "|".join(identity_parts)
        now = time.monotonic()
        window_start = now - policy.window_seconds

        async with self._lock:
            hits = [t for t in self._hits.get(key, []) if t >= window_start]
            if len(hits) >= policy.limit:
                self._hits[key] = hits
                raise RateLimitedError(
                    f"Too many '{operation}' attempts. Please try again later."
                )
            hits.append(now)
            self._hits[key] = hits

    def reset(self) -> None:
        """Test helper: clears all recorded hits."""
        self._hits.clear()


_default_limiter = InMemoryRateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _default_limiter
