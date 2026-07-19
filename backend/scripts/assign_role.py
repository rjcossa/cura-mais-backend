#!/usr/bin/env python
"""Assigns a role to a user directly against the database, bypassing the
`POST /api/v1/admin/users/{user_id}/roles` endpoint's permission check.

This exists for bootstrapping: granting the very first PLATFORM_ADMIN (or
any other role) has no self-serve path through the API, since assigning a
role itself requires the ROLE_ASSIGN permission (see
`tests/test_roles.py`'s `_make_admin_token` for how tests work around the
same chicken-and-egg problem). Once at least one admin account exists,
prefer the API endpoint for everyday role changes — it goes through the
same permission checks and audit trail that a real admin session would.

Reuses `RoleService.assign_role` rather than inserting rows directly, so
you still get the API's own validation (role exists, not already
assigned), the `token_version` bump that invalidates the user's existing
access tokens so the new role takes effect immediately, and the same
security-log / outbox entries a real assignment would produce.

Usage:
    python -m scripts.assign_role --email USER_EMAIL --role ROLE_CODE
    python -m scripts.assign_role --email USER_EMAIL --role ROLE_CODE --reason "..."
    python -m scripts.assign_role --email USER_EMAIL --role ROLE_CODE --expires-at 2027-01-01T00:00:00Z
    python -m scripts.assign_role --list-roles
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import get_session_factory  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.modules.identity.application.role_service import RoleService  # noqa: E402
from app.modules.identity.domain.enums import RoleCode  # noqa: E402
from app.modules.identity.infrastructure.repositories import (  # noqa: E402
    SqlAlchemyOutboxRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemySecurityLogRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", help="Email of the user to grant the role to")
    parser.add_argument("--role", help=f"Role code to assign. One of: {', '.join(r.value for r in RoleCode)}")
    parser.add_argument("--reason", default="Assigned via scripts.assign_role", help="Audit reason (optional)")
    parser.add_argument(
        "--expires-at",
        default=None,
        help="ISO-8601 datetime the role assignment should expire at (optional, defaults to never)",
    )
    parser.add_argument("--list-roles", action="store_true", help="List valid role codes and exit")
    args = parser.parse_args()

    if args.list_roles:
        return args

    if not args.email or not args.role:
        parser.error("--email and --role are required (or pass --list-roles)")

    if args.expires_at:
        try:
            args.expires_at = datetime.datetime.fromisoformat(args.expires_at.replace("Z", "+00:00"))
        except ValueError:
            parser.error(f"--expires-at is not a valid ISO-8601 datetime: {args.expires_at!r}")

    return args


async def assign(email: str, role_code: str, *, reason: str, expires_at: datetime.datetime | None) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        user_repo = SqlAlchemyUserRepository(session)
        role_repo = SqlAlchemyRoleRepository(session)
        service = RoleService(
            user_repo,
            role_repo,
            SqlAlchemySessionRepository(session),
            SqlAlchemySecurityLogRepository(session),
            SqlAlchemyOutboxRepository(session),
        )

        user = await user_repo.get_by_email(email)
        if user is None:
            print(f"No user found with email {email!r}.")
            return

        try:
            await service.assign_role(user.id, role_code, assigned_by=None, expires_at=expires_at, reason=reason)
        except AppError as exc:
            print(f"{exc.code}: {exc.message}")
            return

        await session.commit()

        roles = await service.get_user_roles(user.id)
        print(f"+ {role_code} -> {email} (user {user.id})")
        print(f"  active roles: {', '.join(roles)}")


def main() -> None:
    args = _parse_args()

    if args.list_roles:
        for role in RoleCode:
            print(role.value)
        return

    asyncio.run(assign(args.email, args.role, reason=args.reason, expires_at=args.expires_at))


if __name__ == "__main__":
    main()
