"""Tests for admin role assignment/revocation and permission enforcement
(spec section 25.8)."""

from __future__ import annotations

from sqlalchemy import select

from app.modules.identity.application.tokens import AccessTokenCodec
from app.modules.identity.domain.models import Role, User, UserRole
from tests.conftest import patient_payload

EMAIL = "ana.test@example.com"


async def _make_admin_token(session_factory, permissions: list[str]):
    from app.core.config import get_settings

    async with session_factory() as session:
        admin = User(
            email="admin@example.com", password_hash="x", account_status="ACTIVE", email_verified=True
        )
        session.add(admin)
        await session.flush()
        role = (await session.execute(select(Role).where(Role.code == "PLATFORM_ADMIN"))).scalar_one()
        session.add(UserRole(user_id=admin.id, role_id=role.id, active=True))
        await session.commit()
        admin_id = admin.id

    codec = AccessTokenCodec(get_settings())
    token, _ = codec.build_and_sign(
        user_id=admin_id, session_id=admin_id, roles=["PLATFORM_ADMIN"], permissions=permissions,
        email_verified=True, mobile_verified=False, mfa_verified=False, token_version=1,
    )
    return token, admin_id


async def _get_user_id(session_factory, email: str):
    async with session_factory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        return user.id


async def test_admin_can_assign_role_with_permission(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    target_id = await _get_user_id(session_factory, EMAIL)
    admin_token, _ = await _make_admin_token(session_factory, ["ROLE_ASSIGN"])

    r = await client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"roleCode": "DOCTOR_APPLICANT", "reason": "test"},
    )
    assert r.status_code == 200


async def test_assigning_role_without_permission_is_forbidden(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    target_id = await _get_user_id(session_factory, EMAIL)
    weak_token, _ = await _make_admin_token(session_factory, [])  # no permissions granted

    r = await client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        headers={"Authorization": f"Bearer {weak_token}"},
        json={"roleCode": "DOCTOR_APPLICANT", "reason": "test"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_assigning_duplicate_role_rejected(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    target_id = await _get_user_id(session_factory, EMAIL)
    admin_token, _ = await _make_admin_token(session_factory, ["ROLE_ASSIGN"])

    r = await client.post(
        f"/api/v1/admin/users/{target_id}/roles",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"roleCode": "PATIENT"},  # already has this role from registration
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ROLE_ALREADY_ASSIGNED"


async def test_suspend_user_revokes_sessions_and_blocks_login(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    target_id = await _get_user_id(session_factory, EMAIL)
    admin_token, _ = await _make_admin_token(session_factory, ["USER_ADMIN_SUSPEND"])

    r = await client.post(
        f"/api/v1/admin/users/{target_id}/suspend",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"reason": "policy violation"},
    )
    assert r.status_code == 200

    r2 = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r2.status_code == 403
    assert r2.json()["error"]["code"] == "ACCOUNT_SUSPENDED"


async def test_activate_user_restores_access(client, session_factory):
    await client.post("/api/v1/auth/register/patient", json=patient_payload())
    target_id = await _get_user_id(session_factory, EMAIL)
    admin_token, _ = await _make_admin_token(
        session_factory, ["USER_ADMIN_SUSPEND", "USER_ADMIN_ACTIVATE"]
    )

    await client.post(
        f"/api/v1/admin/users/{target_id}/suspend",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"reason": "test"},
    )
    r = await client.post(
        f"/api/v1/admin/users/{target_id}/activate", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert r.status_code == 200

    r2 = await client.post(
        "/api/v1/auth/login", json={"email": EMAIL, "password": "SecurePassword@123", "device": {}}
    )
    assert r2.status_code == 200
