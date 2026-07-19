"""Provider creation from Identity registration (spec 8.1, 8.2, 37.1)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.providers.domain.models import Provider, ProviderStatusHistory, ProviderVisibilitySettings
from tests.conftest import auth_header


async def test_doctor_registration_creates_provider(client, session_factory):
    r = await client.post(
        "/api/v1/auth/register/doctor",
        json={
            "email": "carlos.creation@example.com",
            "password": "SecurePassword@123",
            "mobileNumber": "+258841111111",
            "firstName": "Carlos",
            "lastName": "Mendes",
            "termsAccepted": True,
            "privacyPolicyAccepted": True,
            "professionalDataConsentAccepted": True,
        },
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["data"]["userId"]

    from app.modules.identity.application.outbox_dispatcher import dispatch_once

    for _ in range(10):
        if await dispatch_once() == 0:
            break

    async with session_factory() as session:
        provider = (
            await session.execute(select(Provider).where(Provider.user_id == uuid.UUID(user_id)))
        ).scalar_one()
        assert provider.provider_type == "DOCTOR"
        assert provider.verification_status == "NOT_VERIFIED"
        assert provider.profile_status == "DRAFT"
        assert provider.publication_status == "UNPUBLISHED"
        assert provider.slug == "carlos-mendes"

        visibility = (
            await session.execute(
                select(ProviderVisibilitySettings).where(ProviderVisibilitySettings.provider_id == provider.id)
            )
        ).scalar_one_or_none()
        assert visibility is not None

        history = (
            await session.execute(select(ProviderStatusHistory).where(ProviderStatusHistory.provider_id == provider.id))
        ).scalars().all()
        assert {h.status_type for h in history} == {"VERIFICATION_STATUS", "PROFILE_STATUS", "PUBLICATION_STATUS"}


async def test_duplicate_creation_event_is_idempotent(session_factory):
    from app.modules.providers.infrastructure.provider_port_adapter import ProviderPortAdapter

    user_id = uuid.uuid4()
    async with session_factory() as session:
        adapter = ProviderPortAdapter(session)
        await adapter.create_provider(user_id, provider_type="DOCTOR", first_name="Ines", last_name="Nhaca")
        await adapter.create_provider(user_id, provider_type="DOCTOR", first_name="Ines", last_name="Nhaca")
        await session.commit()

    async with session_factory() as session:
        rows = (await session.execute(select(Provider).where(Provider.user_id == user_id))).scalars().all()
        assert len(rows) == 1


async def test_slug_collision_generates_unique_variant(session_factory):
    from app.modules.providers.infrastructure.provider_port_adapter import ProviderPortAdapter

    async with session_factory() as session:
        adapter = ProviderPortAdapter(session)
        await adapter.create_provider(uuid.uuid4(), provider_type="DOCTOR", first_name="Paulo", last_name="Mucavele")
        await adapter.create_provider(uuid.uuid4(), provider_type="NUTRITIONIST", first_name="Paulo", last_name="Mucavele")
        await session.commit()

    async with session_factory() as session:
        slugs = sorted(
            (await session.execute(select(Provider.slug).where(Provider.last_name == "Mucavele"))).scalars().all()
        )
        assert slugs == ["paulo-mucavele", "paulo-mucavele-2"]


async def test_unsupported_provider_type_rejected(session_factory):
    from app.modules.providers.domain.exceptions import ProviderError
    from app.modules.providers.infrastructure.provider_port_adapter import ProviderPortAdapter

    async with session_factory() as session:
        adapter = ProviderPortAdapter(session)
        try:
            await adapter.create_provider(uuid.uuid4(), provider_type="ASTROLOGER", first_name="X", last_name="Y")
            assert False, "expected PROVIDER_TYPE_INVALID"
        except ProviderError as exc:
            assert exc.code == "PROVIDER_TYPE_INVALID"

    async with session_factory() as session:
        count = (await session.execute(select(Provider))).scalars().all()
        assert count == []


async def test_get_my_profile_requires_a_provider_record(client, session_factory):
    from tests.conftest import PROVIDER_SELF_PERMISSIONS, make_user_with_role, token_for

    user_id = await make_user_with_role(session_factory, "PATIENT")
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    r = await client.get("/api/v1/providers/me", headers=auth_header(token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "PROVIDER_NOT_FOUND"
