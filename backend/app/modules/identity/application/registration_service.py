"""Patient and doctor-applicant registration (spec section 6)."""

from __future__ import annotations

import datetime

from app.core.config import Settings
from app.core.exceptions import ValidationAppError
from app.modules.identity.application.normalization import (
    normalize_email,
    try_normalize_mobile_number,
)
from app.modules.identity.application.schemas import (
    DoctorRegisterRequest,
    PatientRegisterRequest,
    RegisterResponse,
)
from app.modules.identity.application.security import (
    PasswordHasher,
    PasswordPolicy,
    generate_numeric_otp,
    generate_opaque_token,
    hash_opaque_token,
)
from app.modules.identity.domain.enums import (
    AccountStatus,
    AuthProvider,
    RoleCode,
    VerificationTokenType,
)
from app.modules.identity.domain.events import IdentityEvent, NotificationCommand
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import (
    AuthenticationIdentity,
    IdentitySecurityEvent,
    User,
    UserRole,
    VerificationToken,
)
from app.modules.identity.domain.repositories import (
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    UserRepository,
    VerificationRepository,
)


class RegistrationService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        verification_repo: VerificationRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._roles = role_repo
        self._verifications = verification_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._password_hasher = PasswordHasher()
        self._password_policy = PasswordPolicy(
            min_length=settings.password_min_length, max_length=settings.password_max_length
        )

    async def register_patient(self, request: PatientRegisterRequest) -> RegisterResponse:
        return await self._register(
            email=request.email,
            password=request.password,
            mobile_number=request.mobile_number,
            first_name=request.first_name,
            last_name=request.last_name,
            consents_ok=(
                request.terms_accepted
                and request.privacy_policy_accepted
                and request.health_data_consent_accepted
            ),
            initial_role=RoleCode.PATIENT,
            identity_created_event=IdentityEvent.PATIENT_IDENTITY_CREATED,
        )

    async def register_doctor_applicant(self, request: DoctorRegisterRequest) -> RegisterResponse:
        return await self._register(
            email=request.email,
            password=request.password,
            mobile_number=request.mobile_number,
            first_name=request.first_name,
            last_name=request.last_name,
            consents_ok=(
                request.terms_accepted
                and request.privacy_policy_accepted
                and request.professional_data_consent_accepted
            ),
            initial_role=RoleCode.DOCTOR_APPLICANT,
            identity_created_event=IdentityEvent.DOCTOR_APPLICANT_IDENTITY_CREATED,
            provider_type="DOCTOR",
        )

    async def _register(
        self,
        *,
        email: str,
        password: str,
        mobile_number: str,
        first_name: str,
        last_name: str,
        consents_ok: bool,
        initial_role: RoleCode,
        identity_created_event: str,
        provider_type: str | None = None,
    ) -> RegisterResponse:
        if not consents_ok:
            raise IdentityError.for_code("CONSENT_REQUIRED")

        normalized_email = normalize_email(email)
        normalized_mobile, mobile_error = try_normalize_mobile_number(mobile_number)
        if mobile_error is not None:
            raise ValidationAppError([mobile_error])

        password_errors = self._password_policy.validate(
            password, email=normalized_email, first_name=first_name, last_name=last_name
        )
        if password_errors:
            raise IdentityError.for_code(
                "PASSWORD_POLICY_VIOLATION",
                "The password does not meet the required policy.",
                fields=password_errors,
            )

        if await self._users.get_by_email(normalized_email) is not None:
            raise IdentityError.for_code("EMAIL_ALREADY_REGISTERED")
        if await self._users.get_by_mobile(normalized_mobile) is not None:
            raise IdentityError.for_code("MOBILE_ALREADY_REGISTERED")

        role = await self._roles.get_role_by_code(initial_role.value)
        if role is None:
            # Deployment/seeding issue, not a user error — see
            # scripts/seed_roles_permissions.py.
            raise IdentityError.for_code(
                "ROLE_NOT_FOUND", f"Role '{initial_role.value}' is not configured on this server."
            )

        user = User(
            email=normalized_email,
            mobile_number=normalized_mobile,
            password_hash=self._password_hasher.hash(password),
            account_status=AccountStatus.PENDING_VERIFICATION.value,
        )
        await self._users.add(user)

        await self._users.add_auth_identity(
            AuthenticationIdentity(
                user_id=user.id,
                provider=AuthProvider.LOCAL.value,
                provider_subject=normalized_email,
                provider_email=normalized_email,
                provider_email_verified=False,
            )
        )

        await self._roles.add_user_role(UserRole(user_id=user.id, role_id=role.id, active=True))

        raw_email_token = await self._issue_email_verification_token(user.id)
        raw_otp = await self._issue_mobile_otp(user.id)

        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id,
                event_type="UserRegistered",
                severity="INFO",
                details={"role": initial_role.value},
            )
        )

        verification_url = f"{self._settings.frontend_base_url}/verify-email?token={raw_email_token}"

        await self._outbox.enqueue(
            IdentityEvent.USER_REGISTERED,
            {"userId": str(user.id), "email": normalized_email, "role": initial_role.value},
            aggregate_id=user.id,
        )
        identity_created_payload = {"userId": str(user.id)}
        if provider_type:
            # Spec 8.1's provider-creation trigger — delivered by
            # `identity/application/outbox_dispatcher.py`, which calls
            # `ProviderPortAdapter.create_provider(...)` after this
            # transaction commits. Kept off the `USER_REGISTERED`/
            # notification rows above so a Provider-creation failure can't
            # get entangled with an unrelated notification-send retry.
            identity_created_payload.update(
                {
                    "postRegistrationAction": "CREATE_PROVIDER",
                    "providerType": provider_type,
                    "firstName": first_name,
                    "lastName": last_name,
                    "email": normalized_email,
                }
            )
        await self._outbox.enqueue(identity_created_event, identity_created_payload, aggregate_id=user.id)
        await self._outbox.enqueue(
            IdentityEvent.EMAIL_VERIFICATION_REQUESTED,
            {
                "notificationCommand": NotificationCommand.EMAIL_VERIFICATION,
                "channel": "EMAIL",
                "destination": normalized_email,
                "parameters": {"verificationUrl": verification_url, "firstName": first_name},
            },
            aggregate_id=user.id,
        )
        await self._outbox.enqueue(
            IdentityEvent.MOBILE_VERIFICATION_REQUESTED,
            {
                "notificationCommand": NotificationCommand.MOBILE_OTP,
                "channel": "SMS",
                "destination": normalized_mobile,
                "parameters": {"code": raw_otp},
            },
            aggregate_id=user.id,
        )

        return RegisterResponse(
            user_id=user.id,
            account_status=user.account_status,
            email_verification_required=True,
            mobile_verification_required=True,
        )

    async def _issue_email_verification_token(self, user_id) -> str:
        await self._verifications.invalidate_active_for_user(
            user_id, VerificationTokenType.EMAIL_VERIFICATION.value
        )
        raw_token = generate_opaque_token()
        token_hash = hash_opaque_token(raw_token, self._settings.token_hash_pepper)
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            hours=self._settings.email_verification_token_expire_hours
        )
        await self._verifications.add(
            VerificationToken(
                user_id=user_id,
                token_type=VerificationTokenType.EMAIL_VERIFICATION.value,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        return raw_token

    async def _issue_mobile_otp(self, user_id) -> str:
        await self._verifications.invalidate_active_for_user(
            user_id, VerificationTokenType.MOBILE_OTP.value
        )
        raw_otp = generate_numeric_otp(self._settings.mobile_otp_length)
        otp_hash = hash_opaque_token(raw_otp, self._settings.token_hash_pepper)
        expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
            minutes=self._settings.mobile_otp_expire_minutes
        )
        await self._verifications.add(
            VerificationToken(
                user_id=user_id,
                token_type=VerificationTokenType.MOBILE_OTP.value,
                token_hash=otp_hash,
                expires_at=expires_at,
                max_attempts=self._settings.mobile_otp_max_attempts,
            )
        )
        return raw_otp
