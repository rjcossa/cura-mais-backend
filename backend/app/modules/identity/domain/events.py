"""Domain events published by the Identity module (spec section 21).

Events are written to the `event_outbox` table in the same transaction as
the business change (transactional outbox pattern) — never published
directly to a broker mid-transaction. See `EventOutbox` in `models.py` and
`OutboxRepository.enqueue` in `infrastructure/repositories.py`.
"""

from __future__ import annotations


class IdentityEvent:
    USER_REGISTERED = "UserRegistered"
    PATIENT_IDENTITY_CREATED = "PatientIdentityCreated"
    DOCTOR_APPLICANT_IDENTITY_CREATED = "DoctorApplicantIdentityCreated"

    EMAIL_VERIFICATION_REQUESTED = "EmailVerificationRequested"
    EMAIL_VERIFIED = "EmailVerified"
    MOBILE_VERIFICATION_REQUESTED = "MobileVerificationRequested"
    MOBILE_VERIFIED = "MobileVerified"

    USER_LOGGED_IN = "UserLoggedIn"
    USER_LOGIN_FAILED = "UserLoginFailed"
    USER_LOGIN_BLOCKED = "UserLoginBlocked"
    ACCOUNT_TEMPORARILY_LOCKED = "AccountTemporarilyLocked"

    PASSWORD_RESET_REQUESTED = "PasswordResetRequested"
    PASSWORD_CHANGED = "PasswordChanged"

    SESSION_CREATED = "SessionCreated"
    SESSION_REVOKED = "SessionRevoked"
    ALL_USER_SESSIONS_REVOKED = "AllUserSessionsRevoked"
    REFRESH_TOKEN_REUSED = "RefreshTokenReused"

    MFA_ENROLMENT_STARTED = "MfaEnrolmentStarted"
    MFA_ENABLED = "MfaEnabled"
    MFA_DISABLED = "MfaDisabled"
    RECOVERY_CODE_USED = "RecoveryCodeUsed"

    USER_ROLE_ASSIGNED = "UserRoleAssigned"
    USER_ROLE_REVOKED = "UserRoleRevoked"
    USER_ROLE_CHANGED = "UserRoleChanged"

    USER_SUSPENDED = "UserSuspended"
    USER_ACTIVATED = "UserActivated"
    USER_DEACTIVATED = "UserDeactivated"

    USER_EMAIL_CHANGED = "UserEmailChanged"
    USER_MOBILE_CHANGED = "UserMobileChanged"


class NotificationCommand:
    """Template codes used when Identity asks the Notification module to
    send something (spec section 20.1). The Notification module doesn't
    exist yet in this codebase, so these are dispatched to the mocked
    adapters in `app/core/notifications.py` — swap the dispatcher,
    not the call sites, once that module exists.
    """

    EMAIL_VERIFICATION = "IDENTITY_EMAIL_VERIFICATION"
    MOBILE_OTP = "IDENTITY_MOBILE_OTP"
    PASSWORD_RESET = "IDENTITY_PASSWORD_RESET"
    PASSWORD_CHANGED = "IDENTITY_PASSWORD_CHANGED"
    NEW_DEVICE_LOGIN = "IDENTITY_NEW_DEVICE_LOGIN"
    MFA_ENABLED = "IDENTITY_MFA_ENABLED"
    MFA_DISABLED = "IDENTITY_MFA_DISABLED"
    SUSPICIOUS_LOGIN = "IDENTITY_SUSPICIOUS_LOGIN"
    ACCOUNT_LOCKED = "IDENTITY_ACCOUNT_LOCKED"
    EMAIL_CHANGED = "IDENTITY_EMAIL_CHANGED"
    MOBILE_CHANGED = "IDENTITY_MOBILE_CHANGED"
    ALL_SESSIONS_REVOKED = "IDENTITY_ALL_SESSIONS_REVOKED"
