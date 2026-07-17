"""SQLAlchemy ORM models for every table owned by the Identity module
(spec section 2.2 / section 18).

No other module may import these classes to write directly to these
tables (spec section 19.3) — cross-module access happens exclusively
through `IdentityQueryService` / `IdentityCommandService`
(`app.modules.identity.application.identity_ports`).

Deliberately no ORM `relationship()` graph: repositories query with
explicit `select().join(...)` where a join is needed. For a
bounded-context-per-module architecture this keeps each model
self-contained and avoids accidental cross-table lazy-loads.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()

    email: Mapped[str | None] = mapped_column(CITEXT)
    mobile_number: Mapped[str | None] = mapped_column(String(30))

    password_hash: Mapped[str | None] = mapped_column(String(255))

    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mobile_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    account_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="PENDING_VERIFICATION"
    )

    preferred_language: Mapped[str] = mapped_column(String(20), nullable=False, default="pt-MZ")
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Africa/Maputo")

    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime.datetime | None] = mapped_column()

    token_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    last_login_at: Mapped[datetime.datetime | None] = mapped_column()
    password_changed_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column()

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR mobile_number IS NOT NULL", name="users_identifier_required"
        ),
        CheckConstraint(
            "account_status IN ("
            "'PENDING_VERIFICATION','ACTIVE','LOCKED','SUSPENDED','DEACTIVATED','DELETED')",
            name="users_status_check",
        ),
        Index(
            "ux_users_email",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "ux_users_mobile",
            "mobile_number",
            unique=True,
            postgresql_where=text("mobile_number IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_users_status", "account_status"),
    )


class AuthenticationIdentity(Base):
    __tablename__ = "authentication_identities"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)

    provider_email: Mapped[str | None] = mapped_column(CITEXT)
    provider_email_verified: Mapped[bool | None] = mapped_column(Boolean)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    last_used_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "provider IN ('LOCAL','GOOGLE','APPLE','FACEBOOK')",
            name="authentication_provider_check",
        ),
        UniqueConstraint(
            "provider", "provider_subject", name="ux_authentication_provider_subject"
        ),
        Index("ix_authentication_identities_user", "user_id"),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    id: Mapped[uuid.UUID] = _uuid_pk()

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    assigned_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    expires_at: Mapped[datetime.datetime | None] = mapped_column()
    revoked_at: Mapped[datetime.datetime | None] = mapped_column()
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    revoke_reason: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="ux_user_role"),
        Index("ix_user_roles_user_active", "user_id", "active"),
        Index("ix_user_roles_role", "role_id"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    refresh_token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    device_id: Mapped[str | None] = mapped_column(String(255))
    device_name: Mapped[str | None] = mapped_column(String(255))
    device_platform: Mapped[str | None] = mapped_column(String(40))
    app_version: Mapped[str | None] = mapped_column(String(40))

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)

    issued_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
    last_used_at: Mapped[datetime.datetime | None] = mapped_column()

    revoked_at: Mapped[datetime.datetime | None] = mapped_column()
    revoke_reason: Mapped[str | None] = mapped_column(String(120))

    parent_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_sessions.id")
    )
    replaced_by_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_sessions.id")
    )

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "device_platform IS NULL OR device_platform IN ('WEB','IOS','ANDROID','OTHER')",
            name="user_session_platform_check",
        ),
        Index("ux_user_sessions_refresh_hash", "refresh_token_hash", unique=True),
        Index(
            "ix_user_sessions_user_active",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_user_sessions_token_family", "token_family_id"),
    )


class VerificationToken(Base):
    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    token_type: Mapped[str] = mapped_column(String(50), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    destination: Mapped[str | None] = mapped_column(String(255))

    expires_at: Mapped[datetime.datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column()
    invalidated_at: Mapped[datetime.datetime | None] = mapped_column()

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    token_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "token_type IN ("
            "'EMAIL_VERIFICATION','MOBILE_OTP','PASSWORD_RESET',"
            "'MFA_CHALLENGE','EMAIL_CHANGE','MOBILE_CHANGE')",
            name="verification_token_type_check",
        ),
        Index("ux_verification_token_hash", "token_hash", unique=True),
        Index(
            "ix_verification_tokens_active",
            "user_id",
            "token_type",
            "expires_at",
            postgresql_where=text("used_at IS NULL AND invalidated_at IS NULL"),
        ),
    )


class UserMfaMethod(Base):
    __tablename__ = "user_mfa_methods"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    method: Mapped[str] = mapped_column(String(30), nullable=False)
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    destination_encrypted: Mapped[str | None] = mapped_column(Text)
    destination_masked: Mapped[str | None] = mapped_column(String(100))

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    verified_at: Mapped[datetime.datetime | None] = mapped_column()
    disabled_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("method IN ('AUTHENTICATOR','SMS','EMAIL')", name="user_mfa_method_check"),
        Index(
            "ix_user_mfa_active",
            "user_id",
            postgresql_where=text("enabled = TRUE AND disabled_at IS NULL"),
        ),
        Index(
            "ux_user_primary_mfa",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary = TRUE AND enabled = TRUE AND disabled_at IS NULL"),
        ),
    )


class UserRecoveryCode(Base):
    __tablename__ = "user_recovery_codes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    used_at: Mapped[datetime.datetime | None] = mapped_column()
    invalidated_at: Mapped[datetime.datetime | None] = mapped_column()

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ux_user_recovery_code_hash", "code_hash", unique=True),
        Index(
            "ix_user_recovery_codes_active",
            "user_id",
            postgresql_where=text("used_at IS NULL AND invalidated_at IS NULL"),
        ),
    )


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    identifier_hash: Mapped[str | None] = mapped_column(String(255))
    identifier_type: Mapped[str | None] = mapped_column(String(30))

    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(80))

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[str | None] = mapped_column(String(255))

    occurred_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('SUCCESS','FAILURE','BLOCKED','MFA_REQUIRED')",
            name="login_attempt_outcome_check",
        ),
        Index("ix_login_attempts_user_time", "user_id", "occurred_at"),
        Index("ix_login_attempts_ip_time", "ip_address", "occurred_at"),
        Index("ix_login_attempts_identifier", "identifier_hash", "occurred_at"),
    )


class IdentitySecurityEvent(Base):
    __tablename__ = "identity_security_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_sessions.id")
    )

    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    device_id: Mapped[str | None] = mapped_column(String(255))

    details: Mapped[dict | None] = mapped_column(JSONB)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "severity IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')",
            name="identity_security_severity_check",
        ),
        Index("ix_identity_security_user", "user_id", "created_at"),
        Index("ix_identity_security_severity", "severity", "created_at"),
    )


class PasswordHistory(Base):
    __tablename__ = "password_history"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_password_history_user", "user_id", "created_at"),)


class EventOutbox(Base):
    """Transactional outbox (spec sections 2.2, 21).

    Domain events are inserted into this table in the *same* database
    transaction as the business change that produced them (both go through
    the same `AsyncSession`, committed together by the `get_db` dependency).
    A separate dispatcher process then reads unprocessed rows and hands
    them to the Notification module / message broker — this is what
    guarantees "the notification must not be sent inside the database
    transaction" (spec section 6.2) while still never losing an event to a
    crash between "business write" and "publish".

    This table isn't given explicit DDL in the spec (only listed as an
    owned table in section 2.2), so its shape follows standard
    transactional-outbox practice.
    """

    __tablename__ = "event_outbox"

    id: Mapped[uuid.UUID] = _uuid_pk()

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False, default="User")
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime.datetime] = mapped_column(server_default=func.now())
    processed_at: Mapped[datetime.datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','PROCESSED','FAILED')",
            name="event_outbox_status_check",
        ),
        Index(
            "ix_event_outbox_pending",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )
