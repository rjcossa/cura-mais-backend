"""Identity module error codes (spec section 22) mapped to HTTP status codes.

Services raise `IdentityError.for_code("EMAIL_ALREADY_REGISTERED")` (or the
convenience constants below) rather than picking a status code themselves,
so the mapping stays centralised and consistent with the spec's contract
tests (section 27).
"""

from __future__ import annotations

from app.core.exceptions import AppError, ErrorField

# code -> (http_status, default_message)
_REGISTRY: dict[str, tuple[int, str]] = {
    # 22.1 Registration
    "EMAIL_ALREADY_REGISTERED": (409, "An account with this email address already exists."),
    "MOBILE_ALREADY_REGISTERED": (409, "An account with this mobile number already exists."),
    "INVALID_EMAIL_FORMAT": (422, "The email address format is invalid."),
    "INVALID_MOBILE_FORMAT": (422, "The mobile number format is invalid."),
    "PASSWORD_POLICY_VIOLATION": (422, "The password does not meet the required policy."),
    "CONSENT_REQUIRED": (422, "Required consent was not provided."),
    "REGISTRATION_TYPE_NOT_SUPPORTED": (400, "This registration type is not supported."),
    # 22.2 Authentication
    "INVALID_CREDENTIALS": (401, "The email address or password is incorrect."),
    "ACCOUNT_NOT_VERIFIED": (403, "The account has not completed required verification."),
    "ACCOUNT_LOCKED": (423, "The account is temporarily locked. Please try again later."),
    "ACCOUNT_SUSPENDED": (403, "The account has been suspended."),
    "ACCOUNT_DEACTIVATED": (403, "The account has been deactivated."),
    "MFA_REQUIRED": (401, "Multi-factor authentication is required to complete login."),
    "INVALID_MFA_CODE": (401, "The provided verification code is incorrect."),
    "MFA_CHALLENGE_EXPIRED": (401, "The multi-factor authentication challenge has expired."),
    "MFA_ENROLMENT_EXPIRED": (400, "The authenticator enrolment has expired. Please start again."),
    # 22.3 Tokens
    "ACCESS_TOKEN_INVALID": (401, "The access token is invalid."),
    "ACCESS_TOKEN_EXPIRED": (401, "The access token has expired."),
    "REFRESH_TOKEN_INVALID": (401, "The refresh token is invalid."),
    "REFRESH_TOKEN_EXPIRED": (401, "The refresh token has expired."),
    "REFRESH_TOKEN_REVOKED": (401, "The refresh token has been revoked."),
    "REFRESH_TOKEN_REUSE_DETECTED": (401, "This session has been revoked for your protection."),
    "VERIFICATION_TOKEN_INVALID": (400, "The verification token is invalid."),
    "VERIFICATION_TOKEN_EXPIRED": (400, "The verification token has expired."),
    "VERIFICATION_TOKEN_USED": (400, "This verification token has already been used."),
    # 22.4 Password
    "CURRENT_PASSWORD_INCORRECT": (401, "The current password is incorrect."),
    "NEW_PASSWORD_SAME_AS_CURRENT": (422, "The new password must be different from the current password."),
    "PASSWORD_PREVIOUSLY_USED": (422, "This password has been used recently. Please choose another."),
    "PASSWORD_RESET_TOKEN_INVALID": (400, "The password reset token is invalid."),
    "PASSWORD_RESET_TOKEN_EXPIRED": (400, "The password reset token has expired."),
    # 22.5 Role and permission
    "ROLE_NOT_FOUND": (404, "The requested role does not exist."),
    "ROLE_ALREADY_ASSIGNED": (409, "This role is already assigned to the user."),
    "ROLE_NOT_ASSIGNED": (404, "This role is not currently assigned to the user."),
    "PERMISSION_DENIED": (403, "You do not have permission to perform this action."),
    "LAST_AUTHENTICATION_METHOD_REMOVAL_NOT_ALLOWED": (
        409,
        "You cannot remove your only remaining authentication method.",
    ),
    "MANDATORY_MFA_REQUIRED": (409, "Multi-factor authentication cannot be disabled for this role."),
    # Misc / cross-cutting
    "OTP_INVALID": (401, "The one-time code is incorrect."),
    "OTP_EXPIRED": (400, "The one-time code has expired."),
    "OTP_MAX_ATTEMPTS_EXCEEDED": (429, "Too many incorrect attempts. Please request a new code."),
    "SOCIAL_TOKEN_INVALID": (401, "The identity provider token could not be verified."),
    "SOCIAL_ACCOUNT_LINKING_REQUIRED": (
        409,
        "An account with this email already exists. Please log in and link this provider from your account settings.",
    ),
    "SESSION_NOT_FOUND": (404, "The session was not found."),
    "REAUTHENTICATION_REQUIRED": (401, "Please re-enter your password to continue."),
    "USER_NOT_FOUND": (404, "The user was not found."),
}


class IdentityError(AppError):
    @classmethod
    def for_code(cls, code: str, message: str | None = None, *, fields: list[ErrorField] | None = None) -> IdentityError:
        status_code, default_message = _REGISTRY.get(code, (400, "The request could not be completed."))
        return cls(code=code, message=message or default_message, status_code=status_code, fields=fields)
