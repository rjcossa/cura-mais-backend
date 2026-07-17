"""Centralised application configuration.

All configuration is sourced from environment variables (optionally via a
`.env` file for local development). See `.env.example` at the repository
root for the full list of supported variables and their defaults.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General -----------------------------------------------------
    environment: str = "development"
    app_name: str = "Health Platform Backend"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ------------------------------------------------------
    # Async DSN used by the application at runtime, e.g.:
    # postgresql+asyncpg://user:password@localhost:5432/health_platform
    database_url: str = (
        "postgresql+asyncpg://health_platform:health_platform_dev"
        "@localhost:5432/health_platform"
    )
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 10

    # --- CORS ------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # --- JWT access tokens (RS256) ---------------------------------------
    jwt_private_key_path: Path = BASE_DIR / "keys" / "jwt_private.pem"
    jwt_public_key_path: Path = BASE_DIR / "keys" / "jwt_public.pem"
    jwt_algorithm: str = "RS256"
    jwt_issuer: str = "health-platform-identity"
    jwt_audience: str = "health-platform-api"
    access_token_expire_minutes: int = 15

    # --- Refresh tokens ----------------------------------------------------
    refresh_token_expire_days: int = 30
    refresh_token_remember_expire_days: int = 90

    # --- Secrets used for hashing high-entropy opaque tokens --------------
    # Refresh tokens, OTPs, verification tokens, and recovery codes are all
    # high-entropy random values. They are hashed with HMAC-SHA256 using this
    # server-side pepper rather than Argon2/bcrypt, which are deliberately
    # slow and intended for low-entropy secrets such as passwords.
    token_hash_pepper: str = "CHANGE_ME_dev_only_token_hash_pepper"

    # Fernet key (32 url-safe base64-encoded bytes) used to encrypt MFA
    # TOTP secrets at rest. Generate with `scripts/generate_jwt_keys.py`
    # or `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
    mfa_encryption_key: str = "CHANGE_ME_dev_only_fernet_key_44_chars_______="

    # --- Password policy ---------------------------------------------------
    password_min_length: int = 10
    password_max_length: int = 128
    password_history_size: int = 5

    # --- Account lockout -----------------------------------------------
    failed_login_attempts_before_lock: int = 5
    account_lock_duration_minutes: int = 15
    failed_login_attempt_window_minutes: int = 15

    # Per spec section 5.1, PENDING_VERIFICATION accounts may "log in with
    # limited access where explicitly supported" — so this defaults to
    # False (login allowed pre-verification; downstream actions such as
    # purchasing prescription medicine are expected to gate on
    # `email_verified`/`mobile_verified` themselves). Set True for a
    # stricter "must verify email before any login" policy.
    require_email_verification_to_login: bool = False

    # --- Verification tokens / OTP ----------------------------------------
    email_verification_token_expire_hours: int = 24
    mobile_otp_length: int = 6
    mobile_otp_expire_minutes: int = 5
    mobile_otp_max_attempts: int = 5
    password_reset_token_expire_minutes: int = 60
    mfa_challenge_expire_minutes: int = 5
    mfa_enrolment_expire_minutes: int = 15
    recovery_codes_count: int = 10

    # --- Social login ------------------------------------------------------
    google_client_id: str | None = None
    apple_client_id: str | None = None  # Services ID / audience
    facebook_app_id: str | None = None
    facebook_app_secret: str | None = None

    # --- Notifications -------------------------------------------------
    # SMS has no real provider wired up yet (mock-only for now, per product
    # decision — swap in a real adapter such as Twilio/Vonage behind
    # `SmsAdapter` in app/core/notifications.py when one is chosen).
    sms_provider: str = "mock"

    # Email supports "mock" (console/in-memory, zero config) or "smtp"
    # (real delivery via any SMTP server, e.g. Mailhog locally or a real
    # provider's SMTP endpoint in production).
    email_provider: str = "mock"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    email_from_address: str = "no-reply@health-platform.example"

    frontend_base_url: str = "http://localhost:3000"

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
