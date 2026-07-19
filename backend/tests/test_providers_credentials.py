"""Professional registration and qualification management (spec 10, 11,
33.2, 33.3, 37.3, 37.4)."""

from __future__ import annotations

from tests.conftest import PROVIDER_SELF_PERMISSIONS, auth_header, make_provider, make_user_with_role, token_for


async def _provider_headers(session_factory, **provider_kwargs):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(session_factory, user_id, **provider_kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), provider_id


_REG_PAYLOAD = {
    "registrationType": "MEDICAL_COUNCIL",
    "registrationNumber": "OM-2026-001",
    "registrationAuthority": "Ordem dos Medicos",
    "registrationCountry": "MZ",
    "issueDate": "2014-03-01",
    "expiryDate": "2030-03-01",
    "isPrimary": True,
}


async def test_add_valid_registration(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["verificationStatus"] == "UNVERIFIED"
    assert data["isPrimary"] is True


async def test_duplicate_registration_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers)

    headers2, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers2)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_REGISTRATION_ALREADY_EXISTS"


async def test_invalid_expiry_date_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    bad = {**_REG_PAYLOAD, "registrationNumber": "OM-BAD", "issueDate": "2020-01-01", "expiryDate": "2019-01-01"}
    r = await client.post("/api/v1/providers/me/registrations", json=bad, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_REGISTRATION_INVALID"


async def test_set_new_primary_registration_clears_previous(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r1 = await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers)
    first_id = r1.json()["data"]["id"]

    second = {**_REG_PAYLOAD, "registrationNumber": "OM-2026-002", "isPrimary": False}
    r2 = await client.post("/api/v1/providers/me/registrations", json=second, headers=headers)
    second_id = r2.json()["data"]["id"]

    r3 = await client.post(f"/api/v1/providers/me/registrations/{second_id}/set-primary", headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["isPrimary"] is True

    r4 = await client.get("/api/v1/providers/me/registrations", headers=headers)
    by_id = {row["id"]: row for row in r4.json()["data"]}
    assert by_id[first_id]["isPrimary"] is False
    assert by_id[second_id]["isPrimary"] is True


async def test_delete_decision_locked_registration_rejected(client, session_factory):
    headers, provider_id = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers)
    registration_id = r.json()["data"]["id"]

    from sqlalchemy import select

    from app.modules.providers.domain.models import ProviderProfessionalRegistration

    async with session_factory() as session:
        stmt = select(ProviderProfessionalRegistration).where(ProviderProfessionalRegistration.id == registration_id)
        row = (await session.execute(stmt)).scalar_one()
        row.decision_locked = True
        await session.commit()

    r2 = await client.delete(f"/api/v1/providers/me/registrations/{registration_id}", headers=headers)
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_REGISTRATION_LOCKED"


async def test_editing_verified_registration_supersedes_rather_than_overwrites(client, session_factory):
    headers, provider_id = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/registrations", json=_REG_PAYLOAD, headers=headers)
    registration_id = r.json()["data"]["id"]

    from sqlalchemy import select

    from app.modules.providers.domain.models import ProviderProfessionalRegistration

    async with session_factory() as session:
        stmt = select(ProviderProfessionalRegistration).where(ProviderProfessionalRegistration.id == registration_id)
        row = (await session.execute(stmt)).scalar_one()
        row.verification_status = "VERIFIED"
        await session.commit()

    r2 = await client.patch(
        f"/api/v1/providers/me/registrations/{registration_id}",
        json={"registrationNumber": "OM-2026-999"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    new_registration = r2.json()["data"]
    assert new_registration["id"] != registration_id
    assert new_registration["registrationNumber"] == "OM-2026-999"
    assert new_registration["verificationStatus"] == "UNVERIFIED"

    async with session_factory() as session:
        old = await session.get(ProviderProfessionalRegistration, registration_id)
        assert old.registration_status == "SUPERSEDED"


async def test_add_qualification_unverified_by_default(client, session_factory):
    headers, _ = await _provider_headers(session_factory, provider_type="NUTRITIONIST")
    r = await client.post(
        "/api/v1/providers/me/qualifications",
        json={
            "qualificationType": "UNDERGRADUATE_DEGREE",
            "qualificationName": "BSc Nutrition",
            "institutionName": "Universidade Eduardo Mondlane",
            "institutionCountry": "MZ",
            "startDate": "2010-01-01",
            "completionDate": "2014-01-01",
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["verificationStatus"] == "UNVERIFIED"


async def test_qualification_completion_before_start_date_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/qualifications",
        json={
            "qualificationType": "UNDERGRADUATE_DEGREE",
            "qualificationName": "MD",
            "institutionName": "UEM",
            "startDate": "2015-01-01",
            "completionDate": "2010-01-01",
        },
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_QUALIFICATION_INVALID"


async def test_delete_verified_qualification_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/qualifications",
        json={"qualificationType": "UNDERGRADUATE_DEGREE", "qualificationName": "MD", "institutionName": "UEM"},
        headers=headers,
    )
    qualification_id = r.json()["data"]["id"]

    from app.modules.providers.domain.models import ProviderQualification

    async with session_factory() as session:
        row = await session.get(ProviderQualification, qualification_id)
        row.verification_status = "VERIFIED"
        await session.commit()

    r2 = await client.delete(f"/api/v1/providers/me/qualifications/{qualification_id}", headers=headers)
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_QUALIFICATION_LOCKED"
