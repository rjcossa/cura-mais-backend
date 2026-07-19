"""Profile update, material-change detection, and completeness (spec 9,
37.2)."""

from __future__ import annotations

from tests.conftest import PROVIDER_SELF_PERMISSIONS, auth_header, make_provider, make_user_with_role, token_for


async def _provider_headers(session_factory, **provider_kwargs):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    await make_provider(session_factory, user_id, **provider_kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), user_id


async def test_non_material_update_succeeds_without_reverification_event(client, session_factory):
    headers, _ = await _provider_headers(session_factory)

    r = await client.get("/api/v1/providers/me", headers=headers)
    assert r.status_code == 200, r.text
    profile = r.json()["data"]
    assert profile["verificationStatus"] == "NOT_VERIFIED"

    r = await client.patch(
        "/api/v1/providers/me",
        json={"biography": "General practitioner with 10 years of experience.", "version": profile["version"]},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    updated = r.json()["data"]
    assert updated["biography"] == "General practitioner with 10 years of experience."
    assert updated["version"] == profile["version"] + 1


async def test_material_field_update_on_verified_provider_fires_event(client, session_factory):
    headers, user_id = await _provider_headers(session_factory, verification_status="VERIFIED", profile_status="ACTIVE")

    r = await client.get("/api/v1/providers/me", headers=headers)
    version = r.json()["data"]["version"]

    r = await client.patch("/api/v1/providers/me", json={"lastName": "Chissano", "version": version}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["lastName"] == "Chissano"

    from sqlalchemy import select

    from app.modules.providers.domain.models import EventOutbox

    async with session_factory() as session:
        rows = (
            await session.execute(select(EventOutbox).where(EventOutbox.event_type == "ProviderMaterialChangeDetected"))
        ).scalars().all()
        assert any("last_name" in (row.payload or {}).get("changedFields", []) for row in rows)


async def test_optimistic_lock_conflict_on_stale_version(client, session_factory):
    headers, _ = await _provider_headers(session_factory)

    r = await client.patch("/api/v1/providers/me", json={"biography": "First edit", "version": 999}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_PROFILE_VERSION_CONFLICT"


async def test_completeness_reaches_100_after_final_mandatory_field(client, session_factory):
    headers, user_id = await _provider_headers(session_factory)

    r = await client.get("/api/v1/providers/me/completeness", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["complete"] is False
    assert "biography" in r.json()["data"]["missingFields"]

    r = await client.get("/api/v1/providers/me", headers=headers)
    version = r.json()["data"]["version"]
    await client.patch(
        "/api/v1/providers/me",
        json={
            "professionalTitle": "Dr.",
            "biography": "General practitioner.",
            "yearsOfExperience": 10,
            "version": version,
        },
        headers=headers,
    )

    await client.post(
        "/api/v1/providers/me/registrations",
        json={
            "registrationType": "MEDICAL_COUNCIL",
            "registrationNumber": "OM-1",
            "registrationAuthority": "Ordem dos Medicos",
            "registrationCountry": "MZ",
            "isPrimary": True,
        },
        headers=headers,
    )
    await client.post("/api/v1/providers/me/languages", json={"languageCode": "pt", "proficiency": "NATIVE", "canConsult": True}, headers=headers)

    r = await client.get("/api/v1/reference-data/provider-specialities?providerType=DOCTOR")
    speciality_id = r.json()["data"][0]["id"]
    await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": speciality_id, "isPrimary": True}, headers=headers
    )

    r = await client.get("/api/v1/providers/me/completeness", headers=headers)
    data = r.json()["data"]
    assert "profilePhoto" in data["missingFields"]
    assert data["missingRelationships"] == []


async def test_update_requires_permission(client, session_factory):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    await make_provider(session_factory, user_id)
    token = await token_for(user_id, ["PATIENT"], [])
    r = await client.patch("/api/v1/providers/me", json={"biography": "x", "version": 0}, headers=auth_header(token))
    assert r.status_code == 403
