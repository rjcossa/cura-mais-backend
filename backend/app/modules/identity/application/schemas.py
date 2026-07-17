"""Request/response DTOs for the Identity API.

All models accept and emit **camelCase** JSON, matching the spec's request
examples (e.g. `mobileNumber`, `termsAccepted`) exactly, while Python code
throughout the rest of the module works with normal snake_case attributes.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import EmailStr, Field, field_validator

from app.core.schema_base import CamelModel

# --- Shared -----------------------------------------------------------


class DeviceInfoIn(CamelModel):
    device_id: str | None = None
    device_name: str | None = None
    platform: str | None = Field(default=None, description="WEB | IOS | ANDROID | OTHER")
    app_version: str | None = None
    remember_me: bool = False


# --- Registration (spec section 6) -------------------------------------


class PatientRegisterRequest(CamelModel):
    email: EmailStr
    password: str
    mobile_number: str
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(min_length=1, max_length=150)
    date_of_birth: datetime.date
    terms_accepted: bool
    privacy_policy_accepted: bool
    health_data_consent_accepted: bool

    @field_validator("terms_accepted", "privacy_policy_accepted", "health_data_consent_accepted")
    @classmethod
    def _must_be_true(cls, value: bool) -> bool:
        return value


class DoctorRegisterRequest(CamelModel):
    email: EmailStr
    password: str
    mobile_number: str
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(min_length=1, max_length=150)
    terms_accepted: bool
    privacy_policy_accepted: bool
    professional_data_consent_accepted: bool


class RegisterResponse(CamelModel):
    user_id: uuid.UUID
    account_status: str
    email_verification_required: bool
    mobile_verification_required: bool


# --- Authentication (spec section 7) ------------------------------------


class LoginRequest(CamelModel):
    email: EmailStr
    password: str
    device: DeviceInfoIn = Field(default_factory=DeviceInfoIn)


class TokenPair(CamelModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class LoginSuccessResponse(TokenPair):
    mfa_required: bool = False


class MfaRequiredResponse(CamelModel):
    mfa_required: bool = True
    challenge_id: uuid.UUID
    methods: list[str]


class RefreshTokenRequest(CamelModel):
    refresh_token: str
    device: DeviceInfoIn = Field(default_factory=DeviceInfoIn)


# --- Sessions (spec section 10) ------------------------------------------


class SessionOut(CamelModel):
    id: uuid.UUID
    device_name: str | None
    platform: str | None
    ip_address_masked: str | None
    created_at: datetime.datetime
    last_used_at: datetime.datetime | None
    current: bool


# --- Email verification (spec section 11) --------------------------------


class ResendEmailVerificationRequest(CamelModel):
    email: EmailStr


class VerifyEmailRequest(CamelModel):
    token: str


# --- Mobile verification (spec section 12) --------------------------------


class SendOtpRequest(CamelModel):
    mobile_number: str
    purpose: str = "MOBILE_VERIFICATION"


class VerifyOtpRequest(CamelModel):
    mobile_number: str
    code: str
    purpose: str = "MOBILE_VERIFICATION"


# --- Password management (spec section 13) --------------------------------


class ChangePasswordRequest(CamelModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(CamelModel):
    email: EmailStr


class ResetPasswordRequest(CamelModel):
    token: str
    new_password: str


# --- Social authentication (spec section 14) -------------------------------


class SocialLoginRequest(CamelModel):
    provider: str = Field(description="GOOGLE | APPLE | FACEBOOK")
    identity_token: str
    requested_account_type: str = "PATIENT"
    terms_accepted: bool = True
    privacy_policy_accepted: bool = True
    nonce: str | None = None
    device: DeviceInfoIn = Field(default_factory=DeviceInfoIn)


class LinkSocialProviderRequest(CamelModel):
    provider: str
    identity_token: str
    nonce: str | None = None


# --- MFA (spec section 15) --------------------------------------------------


class EnrolAuthenticatorResponse(CamelModel):
    enrolment_id: uuid.UUID
    secret: str
    otpauth_uri: str
    expires_at: datetime.datetime


class ConfirmAuthenticatorRequest(CamelModel):
    enrolment_id: uuid.UUID
    code: str


class ConfirmAuthenticatorResponse(CamelModel):
    method_id: uuid.UUID
    recovery_codes: list[str]


class VerifyMfaRequest(CamelModel):
    challenge_id: uuid.UUID
    method: str
    code: str


class DisableMfaRequest(CamelModel):
    current_password: str


# --- Roles / permissions (spec section 16) ---------------------------------


class AssignRoleRequest(CamelModel):
    role_code: str
    expires_at: datetime.datetime | None = None
    reason: str | None = None


class UserRoleOut(CamelModel):
    role_code: str
    assigned_at: datetime.datetime
    expires_at: datetime.datetime | None


# --- User management (spec section 17) --------------------------------------


class UpdateCurrentUserRequest(CamelModel):
    preferred_language: str | None = None
    timezone: str | None = None


class ChangeEmailRequest(CamelModel):
    new_email: EmailStr
    current_password: str


class ConfirmEmailChangeRequest(CamelModel):
    token: str


class ChangeMobileRequest(CamelModel):
    new_mobile_number: str
    current_password: str


class ConfirmMobileChangeRequest(CamelModel):
    mobile_number: str
    code: str


class DeactivateAccountRequest(CamelModel):
    current_password: str


class UserProfileOut(CamelModel):
    id: uuid.UUID
    email: str | None
    mobile_number: str | None
    email_verified: bool
    mobile_verified: bool
    account_status: str
    preferred_language: str
    timezone: str
    roles: list[str]
    created_at: datetime.datetime
    last_login_at: datetime.datetime | None
