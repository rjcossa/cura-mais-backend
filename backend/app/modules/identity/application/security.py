"""Low-level security primitives used across the Identity module's
services. This is the *only* place in the codebase that should import
`argon2`, deal with raw HMAC hashing, or touch Fernet encryption — every
other module talks to these functions, never to the underlying crypto
libraries directly.

Hashing strategy:

* **Passwords** (low entropy, user-chosen) -> Argon2id via `argon2-cffi`,
  per spec section 7.3.
* **Everything else that's a high-entropy, server-generated random value**
  (refresh tokens, verification tokens, OTPs, recovery codes) -> HMAC-SHA256
  with a server-side pepper. Argon2's deliberate slowness exists to defend
  low-entropy secrets against offline brute force; it adds cost with no
  security benefit for values that already have >= 128 bits of entropy,
  and would make high-volume refresh-token validation unnecessarily
  expensive. HMAC-SHA256 with a secret pepper still protects against a
  database-only leak (the attacker needs the pepper too), which is what
  "stored only as a hash" (spec sections 9.1, 11.3, 15.6) is protecting
  against.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string

from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2 import exceptions as argon2_exceptions
from cryptography.fernet import Fernet, InvalidToken

from app.core.exceptions import ErrorField

_argon2 = _Argon2PasswordHasher()

_SPECIAL_CHARS = set("!@#$%^&*()-_=+[]{}|;:'\",.<>/?`~\\")

# A deliberately small, representative blocklist of extremely common
# passwords. In production, replace/augment this with a k-anonymity
# lookup against the Have I Been Pwned Pwned Passwords API (no plaintext
# password ever leaves the server in that scheme) — omitted here so the
# module has zero external network dependency for local development.
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "123456789", "12345678",
    "qwerty123", "letmein123", "admin1234", "welcome123", "iloveyou1",
    "changeme1", "passw0rd1", "abc12345", "sunshine1", "princess1",
    "football1", "baseball1", "dragon123", "monkey123", "trustno1",
}


class PasswordHasher:
    @staticmethod
    def hash(plain_password: str) -> str:
        return _argon2.hash(plain_password)

    @staticmethod
    def verify(plain_password: str, password_hash: str) -> bool:
        try:
            return _argon2.verify(password_hash, plain_password)
        except (
            argon2_exceptions.VerifyMismatchError,
            argon2_exceptions.VerificationError,
            argon2_exceptions.InvalidHash,
        ):
            return False

    @staticmethod
    def needs_rehash(password_hash: str) -> bool:
        try:
            return _argon2.check_needs_rehash(password_hash)
        except argon2_exceptions.InvalidHash:
            return True


class PasswordPolicy:
    """Implements spec section 13.1."""

    def __init__(self, min_length: int = 10, max_length: int = 128) -> None:
        self.min_length = min_length
        self.max_length = max_length

    def validate(
        self,
        password: str,
        *,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> list[ErrorField]:
        errors: list[ErrorField] = []

        if len(password) < self.min_length:
            errors.append(
                ErrorField("password", f"Password must be at least {self.min_length} characters.")
            )
        if len(password) > self.max_length:
            errors.append(
                ErrorField("password", f"Password must be at most {self.max_length} characters.")
            )
        if not re.search(r"[A-Z]", password):
            errors.append(ErrorField("password", "Password must contain an uppercase letter."))
        if not re.search(r"[a-z]", password):
            errors.append(ErrorField("password", "Password must contain a lowercase letter."))
        if not re.search(r"\d", password):
            errors.append(ErrorField("password", "Password must contain a number."))
        if not any(char in _SPECIAL_CHARS for char in password):
            errors.append(ErrorField("password", "Password must contain a special character."))
        if password.lower() in _COMMON_PASSWORDS:
            errors.append(ErrorField("password", "This password is too common. Please choose another."))

        lowered = password.lower()
        for candidate in filter(None, [email and email.split("@")[0], first_name, last_name]):
            if len(candidate) >= 4 and candidate.lower() in lowered:
                errors.append(
                    ErrorField("password", "Password must not contain your name or email address.")
                )
                break

        return errors


# --- Opaque high-entropy tokens (refresh tokens, verification tokens) ----


def generate_opaque_token(num_bytes: int = 32) -> str:
    """>= 256 bits of entropy, URL-safe. Used for refresh tokens and
    email/verification tokens (spec sections 9.1, 11.3)."""
    return secrets.token_urlsafe(num_bytes)


def hash_opaque_token(raw_token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), raw_token.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_numeric_otp(length: int = 6) -> str:
    """Cryptographically random numeric OTP (spec section 12.3)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_recovery_code() -> str:
    """Human-typeable recovery code, e.g. `7K4G-QX2M-9F3D`."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


# --- Masking for display (session lists, notifications) ------------------


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked_local = local[0] + "*"
    else:
        masked_local = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked_local}@{domain}"


def mask_mobile(mobile: str) -> str:
    if len(mobile) <= 4:
        return "*" * len(mobile)
    return mobile[:3] + "X" * (len(mobile) - 5) + mobile[-2:]


def mask_ip(ip_address) -> str | None:
    if not ip_address:
        return None
    # asyncpg maps INET columns to ipaddress.IPv4Address/IPv6Address
    # objects, not plain strings — normalise before masking.
    ip_str = str(ip_address)
    parts = ip_str.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.XX.XX.{parts[3]}"
    return ip_str  # IPv6 or unexpected format: leave as-is.


# --- MFA secret encryption at rest ---------------------------------------


class MfaSecretCipher:
    """Encrypts TOTP secrets before persisting (spec section 15.3)."""

    def __init__(self, fernet_key: str) -> None:
        self._fernet = Fernet(fernet_key.encode("utf-8"))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt MFA secret; key may have changed.") from exc
