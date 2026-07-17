"""Social login, account linking, and unlinking (spec section 14)."""

from __future__ import annotations

import datetime

from app.core.config import Settings
from app.modules.identity.application.mfa_service import MfaService
from app.modules.identity.application.schemas import (
    DeviceInfoIn,
    LoginSuccessResponse,
    MfaRequiredResponse,
)
from app.modules.identity.application.tokens import DeviceInfo, TokenService
from app.modules.identity.domain.enums import AccountStatus, RoleCode
from app.modules.identity.domain.events import IdentityEvent
from app.modules.identity.domain.exceptions import IdentityError
from app.modules.identity.domain.models import (
    AuthenticationIdentity,
    IdentitySecurityEvent,
    User,
    UserRole,
)
from app.modules.identity.domain.repositories import (
    MfaRepository,
    OutboxRepository,
    RoleRepository,
    SecurityLogRepository,
    UserRepository,
)
from app.modules.identity.infrastructure.social_providers import SocialIdentityProvider


def _to_device(device_in: DeviceInfoIn, ip_address: str | None, user_agent: str | None) -> DeviceInfo:
    return DeviceInfo(
        device_id=device_in.device_id,
        device_name=device_in.device_name,
        platform=device_in.platform,
        app_version=device_in.app_version,
        ip_address=ip_address,
        user_agent=user_agent,
        remember_me=device_in.remember_me,
    )


class SocialAuthService:
    def __init__(
        self,
        settings: Settings,
        user_repo: UserRepository,
        role_repo: RoleRepository,
        mfa_repo: MfaRepository,
        security_log_repo: SecurityLogRepository,
        outbox_repo: OutboxRepository,
        token_service: TokenService,
        mfa_service: MfaService,
        providers: dict[str, SocialIdentityProvider],
    ) -> None:
        self._settings = settings
        self._users = user_repo
        self._roles = role_repo
        self._mfa = mfa_repo
        self._security_log = security_log_repo
        self._outbox = outbox_repo
        self._tokens = token_service
        self._mfa_service = mfa_service
        self._providers = providers

    def _provider_for(self, provider_code: str) -> SocialIdentityProvider:
        provider = self._providers.get(provider_code.upper())
        if provider is None:
            raise IdentityError.for_code("SOCIAL_TOKEN_INVALID", f"Unsupported provider '{provider_code}'.")
        return provider

    async def login_or_register(
        self,
        provider_code: str,
        identity_token: str,
        requested_account_type: str,
        device_in: DeviceInfoIn,
        *,
        nonce: str | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> LoginSuccessResponse | MfaRequiredResponse:
        provider = self._provider_for(provider_code)
        result = await provider.validate_token(identity_token, nonce=nonce)
        device = _to_device(device_in, ip_address, user_agent)

        existing_identity = await self._users.get_auth_identity(provider_code.upper(), result.provider_subject)

        if existing_identity is not None:
            # --- 14.4 Existing Identity Flow ---
            user = await self._users.get_by_id(existing_identity.user_id)
            if user is None:
                raise IdentityError.for_code("SOCIAL_TOKEN_INVALID")
            self._assert_active_for_login(user)

            existing_identity.last_used_at = datetime.datetime.now(datetime.UTC)

            enabled_methods = await self._mfa.list_enabled_methods(user.id)
            if enabled_methods:
                challenge = await self._mfa_service.create_login_challenge(user, device)
                return MfaRequiredResponse(
                    challenge_id=challenge.id, methods=sorted({m.method for m in enabled_methods})
                )

            issued = await self._tokens.issue_session(user, device)
            user.last_login_at = datetime.datetime.now(datetime.UTC)
            await self._outbox.enqueue(
                IdentityEvent.USER_LOGGED_IN,
                {"userId": str(user.id), "sessionId": str(issued.session.id), "provider": provider_code},
                aggregate_id=user.id,
            )
            return LoginSuccessResponse(
                access_token=issued.access_token,
                refresh_token=issued.raw_refresh_token,
                expires_in=issued.access_token_expires_in,
                mfa_required=False,
            )

        # --- 14.5 New Identity Flow ---
        if result.email and result.email_verified:
            existing_user_by_email = await self._users.get_by_email(result.email.lower())
            if existing_user_by_email is not None:
                # 14.6: don't silently take over an existing account — the
                # user must authenticate normally and link the provider
                # from account settings instead.
                raise IdentityError.for_code("SOCIAL_ACCOUNT_LINKING_REQUIRED")

        role_code = (
            RoleCode.DOCTOR_APPLICANT if requested_account_type.upper() == "DOCTOR" else RoleCode.PATIENT
        )
        role = await self._roles.get_role_by_code(role_code.value)
        if role is None:
            raise IdentityError.for_code("ROLE_NOT_FOUND", f"Role '{role_code.value}' is not configured.")

        user = User(
            email=result.email.lower() if result.email else None,
            email_verified=bool(result.email and result.email_verified),
            account_status=AccountStatus.PENDING_VERIFICATION.value,
        )
        await self._users.add(user)
        await self._users.add_auth_identity(
            AuthenticationIdentity(
                user_id=user.id,
                provider=provider_code.upper(),
                provider_subject=result.provider_subject,
                provider_email=result.email,
                provider_email_verified=result.email_verified,
                last_used_at=datetime.datetime.now(datetime.UTC),
            )
        )
        await self._roles.add_user_role(UserRole(user_id=user.id, role_id=role.id, active=True))

        await self._security_log.add_security_event(
            IdentitySecurityEvent(user_id=user.id, event_type="UserRegistered", severity="INFO")
        )
        await self._outbox.enqueue(
            IdentityEvent.USER_REGISTERED,
            {"userId": str(user.id), "provider": provider_code, "role": role_code.value},
            aggregate_id=user.id,
        )
        await self._outbox.enqueue(
            IdentityEvent.PATIENT_IDENTITY_CREATED
            if role_code == RoleCode.PATIENT
            else IdentityEvent.DOCTOR_APPLICANT_IDENTITY_CREATED,
            {"userId": str(user.id)},
            aggregate_id=user.id,
        )

        issued = await self._tokens.issue_session(user, device)
        user.last_login_at = datetime.datetime.now(datetime.UTC)
        return LoginSuccessResponse(
            access_token=issued.access_token,
            refresh_token=issued.raw_refresh_token,
            expires_in=issued.access_token_expires_in,
            mfa_required=False,
        )

    async def link_provider(
        self, user: User, provider_code: str, identity_token: str, *, nonce: str | None
    ) -> None:
        provider = self._provider_for(provider_code)
        result = await provider.validate_token(identity_token, nonce=nonce)

        conflicting = await self._users.get_auth_identity(provider_code.upper(), result.provider_subject)
        if conflicting is not None and conflicting.user_id != user.id:
            raise IdentityError.for_code(
                "SOCIAL_ACCOUNT_LINKING_REQUIRED", "This provider account is already linked to another user."
            )
        if conflicting is not None:
            return  # Already linked to this same user; idempotent no-op.

        await self._users.add_auth_identity(
            AuthenticationIdentity(
                user_id=user.id,
                provider=provider_code.upper(),
                provider_subject=result.provider_subject,
                provider_email=result.email,
                provider_email_verified=result.email_verified,
                last_used_at=datetime.datetime.now(datetime.UTC),
            )
        )
        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id, event_type="SocialProviderLinked", severity="INFO",
                details={"provider": provider_code.upper()},
            )
        )

    async def unlink_provider(self, user: User, provider_code: str) -> None:
        identities = await self._users.list_auth_identities(user.id)
        target = next((i for i in identities if i.provider == provider_code.upper()), None)
        if target is None:
            raise IdentityError.for_code("USER_NOT_FOUND", "This provider is not linked to your account.")

        remaining = [i for i in identities if i.id != target.id]
        has_password = user.password_hash is not None
        if not remaining and not has_password:
            raise IdentityError.for_code("LAST_AUTHENTICATION_METHOD_REMOVAL_NOT_ALLOWED")

        await self._users.delete_auth_identity(target)
        await self._security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id, event_type="SocialProviderUnlinked", severity="MEDIUM",
                details={"provider": provider_code.upper()},
            )
        )

    @staticmethod
    def _assert_active_for_login(user: User) -> None:
        if user.account_status == AccountStatus.SUSPENDED.value:
            raise IdentityError.for_code("ACCOUNT_SUSPENDED")
        if user.account_status == AccountStatus.DEACTIVATED.value:
            raise IdentityError.for_code("ACCOUNT_DEACTIVATED")
        if user.account_status == AccountStatus.DELETED.value:
            raise IdentityError.for_code("SOCIAL_TOKEN_INVALID")
        if user.account_status == AccountStatus.LOCKED.value:
            now = datetime.datetime.now(datetime.UTC)
            if user.locked_until is not None and user.locked_until > now:
                raise IdentityError.for_code("ACCOUNT_LOCKED")
