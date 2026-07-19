#!/usr/bin/env python
"""Creates a user directly against the database and assigns it a role —
the other half of the bootstrap problem `scripts/assign_role.py` solves.

`POST /api/v1/auth/register/*` only ever creates PATIENT or
DOCTOR_APPLICANT accounts, starts them as PENDING_VERIFICATION, and
requires email/mobile verification before they're fully trusted. That's
right for real end users, but useless for standing up the very first
back-office/admin account (or a throwaway account for manual API
testing) — there's no registration endpoint for BACK_OFFICE_REVIEWER,
BACK_OFFICE_APPROVER, or PLATFORM_ADMIN, and waiting on email/SMS
verification for a test account is pure friction.

This script creates the user pre-verified and ACTIVE (so it can log in
immediately), reusing the same password policy, password hashing, and
email/mobile normalization the registration flow uses, then grants the
requested role through `RoleService.assign_role` — the same call
`scripts/assign_role.py` and the admin API endpoint make, so the account
ends up in exactly the state a normal role assignment would leave it in.

`--create-provider` (opt-in, only meaningful with `--role
DOCTOR_APPLICANT`/`NUTRITIONIST_APPLICANT`) additionally creates a
`providers` row in the same transaction, via the same
`ProviderPortAdapter.create_provider` call the real registration flow
uses (`identity/application/outbox_dispatcher.py`) — so a
script-bootstrapped applicant behaves like a normal one. It's opt-in
rather than automatic so this script doesn't hard-fail in a dev
environment where the Providers migration hasn't run yet, and doesn't
become a second registration code path that has to be kept in sync with
`RegistrationService._register()` forever. This is deliberately not
chased into `scripts/assign_role.py` or the real admin role-assignment
API — see `app.modules.providers.infrastructure.provider_port_adapter`'s
docstring for why a missing `providers` row surfaces loudly instead.

Usage:
    python -m scripts.create_user --email USER_EMAIL --password PASSWORD --role ROLE_CODE
    python -m scripts.create_user --email USER_EMAIL --role ROLE_CODE   # password auto-generated and printed
    python -m scripts.create_user --email admin@example.com --role PLATFORM_ADMIN --mobile +258840000000
    python -m scripts.create_user --email doctor@example.com --role DOCTOR_APPLICANT --create-provider
    python -m scripts.create_user --list-roles
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.database import get_session_factory  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.modules.identity.application.normalization import (  # noqa: E402
    normalize_email,
    try_normalize_mobile_number,
)
from app.modules.identity.application.role_service import RoleService  # noqa: E402
from app.modules.identity.application.security import PasswordHasher, PasswordPolicy  # noqa: E402
from app.modules.identity.domain.enums import AccountStatus, AuthProvider, RoleCode  # noqa: E402
from app.modules.identity.domain.models import AuthenticationIdentity, IdentitySecurityEvent, User  # noqa: E402
from app.modules.identity.infrastructure.repositories import (  # noqa: E402
    SqlAlchemyOutboxRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySecurityLogRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)


def _generate_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
        ):
            return candidate


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", help="Email for the new user")
    parser.add_argument("--role", help=f"Role code to assign. One of: {', '.join(r.value for r in RoleCode)}")
    parser.add_argument("--password", default=None, help="Password (auto-generated and printed if omitted)")
    parser.add_argument("--mobile", default=None, help="Mobile number, e.g. +258840000000 (optional)")
    parser.add_argument("--first-name", default="", help="First name, used only for the security log entry")
    parser.add_argument("--last-name", default="", help="Last name, used only for the security log entry")
    parser.add_argument("--reason", default="Created via scripts.create_user", help="Audit reason for the role grant")
    parser.add_argument(
        "--create-provider",
        action="store_true",
        help="Also create a providers row (only valid with --role DOCTOR_APPLICANT/NUTRITIONIST_APPLICANT)",
    )
    parser.add_argument("--list-roles", action="store_true", help="List valid role codes and exit")
    args = parser.parse_args()

    if args.list_roles:
        return args

    if not args.email or not args.role:
        parser.error("--email and --role are required (or pass --list-roles)")

    return args


_PROVIDER_TYPE_BY_APPLICANT_ROLE = {
    "DOCTOR_APPLICANT": "DOCTOR",
    "NUTRITIONIST_APPLICANT": "NUTRITIONIST",
}


async def create(
    email: str,
    role_code: str,
    *,
    password: str | None,
    mobile: str | None,
    first_name: str,
    last_name: str,
    reason: str,
    create_provider: bool = False,
) -> None:
    if create_provider and role_code not in _PROVIDER_TYPE_BY_APPLICANT_ROLE:
        print(f"--create-provider requires --role to be one of: {', '.join(_PROVIDER_TYPE_BY_APPLICANT_ROLE)}")
        return
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        user_repo = SqlAlchemyUserRepository(session)
        role_repo = SqlAlchemyRoleRepository(session)
        role_service = RoleService(
            user_repo,
            role_repo,
            SqlAlchemySessionRepository(session),
            SqlAlchemySecurityLogRepository(session),
            SqlAlchemyOutboxRepository(session),
        )

        normalized_email = normalize_email(email)
        normalized_mobile = None
        if mobile:
            normalized_mobile, mobile_error = try_normalize_mobile_number(mobile)
            if mobile_error is not None:
                print(f"Invalid mobile number: {mobile_error.message}")
                return

        if await user_repo.get_by_email(normalized_email) is not None:
            print(f"A user with email {normalized_email!r} already exists — use scripts.assign_role instead.")
            return
        if normalized_mobile and await user_repo.get_by_mobile(normalized_mobile) is not None:
            print(f"A user with mobile number {normalized_mobile!r} already exists.")
            return

        role = await role_repo.get_role_by_code(role_code)
        if role is None:
            print(f"ROLE_NOT_FOUND: {role_code!r} is not configured on this server (run seed_roles_permissions.py?)")
            return

        generated_password = password is None
        password = password or _generate_password()
        policy = PasswordPolicy(min_length=settings.password_min_length, max_length=settings.password_max_length)
        password_errors = policy.validate(password, email=normalized_email, first_name=first_name, last_name=last_name)
        if password_errors:
            print("Password does not meet policy:")
            for err in password_errors:
                print(f"  - {err.message}")
            return

        user = User(
            email=normalized_email,
            mobile_number=normalized_mobile,
            password_hash=PasswordHasher.hash(password),
            account_status=AccountStatus.ACTIVE.value,
            email_verified=True,
            mobile_verified=bool(normalized_mobile),
        )
        await user_repo.add(user)

        await user_repo.add_auth_identity(
            AuthenticationIdentity(
                user_id=user.id,
                provider=AuthProvider.LOCAL.value,
                provider_subject=normalized_email,
                provider_email=normalized_email,
                provider_email_verified=True,
            )
        )

        try:
            await role_service.assign_role(user.id, role_code, assigned_by=None, reason=reason)
        except AppError as exc:
            print(f"{exc.code}: {exc.message}")
            await session.rollback()
            return

        if create_provider:
            from app.modules.providers.infrastructure.provider_port_adapter import ProviderPortAdapter

            await ProviderPortAdapter(session).create_provider(
                user.id,
                provider_type=_PROVIDER_TYPE_BY_APPLICANT_ROLE[role_code],
                first_name=first_name,
                last_name=last_name,
                email=normalized_email,
            )

        security_log = SqlAlchemySecurityLogRepository(session)
        await security_log.add_security_event(
            IdentitySecurityEvent(
                user_id=user.id,
                event_type="UserCreated",
                severity="INFO",
                details={"createdVia": "scripts.create_user", "role": role_code},
            )
        )

        await session.commit()

        print(f"+ user {normalized_email} ({user.id})")
        print(f"  role: {role_code}")
        print(f"  status: ACTIVE, email_verified=True, mobile_verified={bool(normalized_mobile)}")
        if create_provider:
            print(f"  provider: created ({_PROVIDER_TYPE_BY_APPLICANT_ROLE[role_code]})")
        if generated_password:
            print(f"  password (generated — save this, it won't be shown again): {password}")


def main() -> None:
    args = _parse_args()

    if args.list_roles:
        for role in RoleCode:
            print(role.value)
        return

    asyncio.run(
        create(
            args.email,
            args.role,
            password=args.password,
            mobile=args.mobile,
            first_name=args.first_name,
            last_name=args.last_name,
            reason=args.reason,
            create_provider=args.create_provider,
        )
    )


if __name__ == "__main__":
    main()
