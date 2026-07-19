"""Back-office search/suspend/reinstate and public-profile redaction
(spec 20, 22, 37.12)."""

from __future__ import annotations

import uuid

from tests.conftest import PROVIDER_BACKOFFICE_PERMISSIONS, PROVIDER_SELF_PERMISSIONS, auth_header, make_provider, make_user_with_role, token_for


async def _provider_headers(session_factory, **provider_kwargs):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(session_factory, user_id, **provider_kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), provider_id, user_id


async def _backoffice_headers(session_factory):
    user_id = await make_user_with_role(session_factory, "BACK_OFFICE_APPROVER")
    token = await token_for(user_id, ["BACK_OFFICE_APPROVER"], PROVIDER_BACKOFFICE_PERMISSIONS)
    return auth_header(token)


async def test_search_providers_by_verification_status(client, session_factory):
    await _provider_headers(session_factory, verification_status="VERIFIED", profile_status="ACTIVE", first_name="Zeca", last_name="Verified")
    await _provider_headers(session_factory, verification_status="NOT_VERIFIED")

    bo_headers = await _backoffice_headers(session_factory)
    r = await client.get("/api/v1/back-office/providers?verificationStatus=VERIFIED", headers=bo_headers)
    assert r.status_code == 200, r.text
    assert all(p["verificationStatus"] == "VERIFIED" for p in r.json()["data"]["content"])
    assert any(p["displayName"] == "Zeca Verified" for p in r.json()["data"]["content"])


async def test_search_requires_permission(client, session_factory):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    token = await token_for(user_id, ["PATIENT"], [])
    r = await client.get("/api/v1/back-office/providers", headers=auth_header(token))
    assert r.status_code == 403


async def test_get_provider_detail_includes_history(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory)
    bo_headers = await _backoffice_headers(session_factory)
    r = await client.get(f"/api/v1/back-office/providers/{provider_id}", headers=bo_headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["provider"]["id"] == str(provider_id)
    # `make_provider` is a direct-DB-insert test shortcut, not the real
    # creation flow (`ProfileService.create_provider`), so no status
    # history rows are expected here — that path is covered by
    # test_providers_creation.py::test_doctor_registration_creates_provider.
    # This test's purpose is just confirming the detail endpoint's shape.
    assert "statusHistory" in data and "publicationHistory" in data


async def test_suspend_provider_hides_and_suspends_active_services(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory, verification_status="VERIFIED", profile_status="ACTIVE")

    svc = await client.post(
        "/api/v1/providers/me/services",
        json={"serviceCode": "S1", "name": "S1", "durationMinutes": 30, "price": 10.0, "currency": "MZN", "deliveryModes": ["VIDEO"]},
        headers=headers,
    )
    service_id = svc.json()["data"]["id"]
    await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)

    bo_headers = await _backoffice_headers(session_factory)
    r = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/suspend",
        json={"reasonCode": "PROFESSIONAL_LICENCE_EXPIRED", "comments": "Licence expired."},
        headers=bo_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["verificationStatus"] == "SUSPENDED"
    assert data["profileStatus"] == "SUSPENDED"
    assert data["publicationStatus"] == "HIDDEN"

    from app.modules.providers.domain.models import ProviderService

    async with session_factory() as session:
        service = await session.get(ProviderService, uuid.UUID(service_id))
        assert service.status == "SUSPENDED"


async def test_reinstate_provider(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory, verification_status="SUSPENDED", profile_status="SUSPENDED", publication_status="HIDDEN")
    bo_headers = await _backoffice_headers(session_factory)
    r = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/reinstate", json={"approvalReference": "ONB-REINSTATE-1"}, headers=bo_headers
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["verificationStatus"] == "VERIFIED"
    assert data["profileStatus"] == "ACTIVE"
    assert data["publicationStatus"] == "HIDDEN"  # not auto-republished


async def test_get_published_provider_public_profile(client, session_factory):
    headers, provider_id, _ = await _provider_headers(
        session_factory, verification_status="VERIFIED", profile_status="ACTIVE", publication_status="PUBLISHED"
    )
    r = await client.get(f"/api/v1/public/providers/{provider_id}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["id"] == str(provider_id)
    assert data["verificationBadge"] == "VERIFIED"
    assert "specialities" in data and "services" in data and "locations" in data


async def test_get_unpublished_provider_returns_404(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory)  # defaults to UNPUBLISHED
    r = await client.get(f"/api/v1/public/providers/{provider_id}")
    assert r.status_code == 404


async def test_get_hidden_provider_returns_404_but_backoffice_still_sees_it(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory, publication_status="HIDDEN")
    r = await client.get(f"/api/v1/public/providers/{provider_id}")
    assert r.status_code == 404

    bo_headers = await _backoffice_headers(session_factory)
    r2 = await client.get(f"/api/v1/back-office/providers/{provider_id}", headers=bo_headers)
    assert r2.status_code == 200, r2.text


async def test_public_profile_excludes_sensitive_fields(client, session_factory):
    headers, provider_id, _ = await _provider_headers(
        session_factory, verification_status="VERIFIED", profile_status="ACTIVE", publication_status="PUBLISHED"
    )
    r = await client.get(f"/api/v1/public/providers/{provider_id}")
    assert r.status_code == 200, r.text
    raw = r.text
    for forbidden in ("dateOfBirth", "userId", "nationalIdNumber", "mobileNumber", "email", "approvalReference"):
        assert forbidden not in raw, f"public response leaked {forbidden!r}"


async def test_get_public_provider_by_slug(client, session_factory):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(
        session_factory,
        user_id,
        verification_status="VERIFIED",
        profile_status="ACTIVE",
        publication_status="PUBLISHED",
        slug="dr-slug-lookup-test",
    )
    r = await client.get("/api/v1/public/providers/slug/dr-slug-lookup-test")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["id"] == str(provider_id)
