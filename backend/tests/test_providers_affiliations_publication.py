"""Institution affiliations and publication workflow (spec 17, 19, 33.7,
37.9, 37.10)."""

from __future__ import annotations

import uuid

from tests.conftest import (
    PROVIDER_BACKOFFICE_PERMISSIONS,
    PROVIDER_SELF_PERMISSIONS,
    auth_header,
    make_provider,
    make_user_with_role,
    token_for,
)


async def _provider_headers(session_factory, **provider_kwargs):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(session_factory, user_id, **provider_kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), provider_id, user_id


async def _backoffice_headers(session_factory):
    user_id = await make_user_with_role(session_factory, "BACK_OFFICE_APPROVER")
    token = await token_for(user_id, ["BACK_OFFICE_APPROVER"], PROVIDER_BACKOFFICE_PERMISSIONS)
    return auth_header(token)


async def test_request_valid_affiliation_is_pending(client, session_factory):
    headers, _, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/affiliations",
        json={"institutionId": str(uuid.uuid4()), "affiliationType": "EMPLOYED", "professionalPosition": "GP"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "PENDING"
    assert r.json()["data"]["affiliationSource"] == "SELF_DECLARED"


async def test_duplicate_active_affiliation_rejected(client, session_factory):
    headers, _, _ = await _provider_headers(session_factory)
    institution_id = str(uuid.uuid4())
    payload = {"institutionId": institution_id, "affiliationType": "EMPLOYED"}
    await client.post("/api/v1/providers/me/affiliations", json=payload, headers=headers)
    r = await client.post("/api/v1/providers/me/affiliations", json=payload, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_AFFILIATION_ALREADY_EXISTS"


async def test_confirm_affiliation_by_back_office(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/affiliations",
        json={"institutionId": str(uuid.uuid4()), "affiliationType": "VISITING"},
        headers=headers,
    )
    affiliation_id = r.json()["data"]["id"]

    bo_headers = await _backoffice_headers(session_factory)
    r2 = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/affiliations/{affiliation_id}/confirm", headers=bo_headers
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "ACTIVE"
    assert r2.json()["data"]["confirmedAt"] is not None


async def test_reject_affiliation_requires_reason(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/affiliations",
        json={"institutionId": str(uuid.uuid4()), "affiliationType": "CONTRACTED"},
        headers=headers,
    )
    affiliation_id = r.json()["data"]["id"]

    bo_headers = await _backoffice_headers(session_factory)
    r2 = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/affiliations/{affiliation_id}/reject", json={}, headers=bo_headers
    )
    assert r2.status_code == 422, r2.text

    r3 = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/affiliations/{affiliation_id}/reject",
        json={"reason": "Institution could not confirm this employment relationship."},
        headers=bo_headers,
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["status"] == "REJECTED"


async def test_end_affiliation(client, session_factory):
    headers, provider_id, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/affiliations",
        json={"institutionId": str(uuid.uuid4()), "affiliationType": "OWNER", "startDate": "2020-01-01"},
        headers=headers,
    )
    affiliation_id = r.json()["data"]["id"]

    r2 = await client.post(
        f"/api/v1/providers/me/affiliations/{affiliation_id}/end",
        json={"endDate": "2026-12-31", "reason": "Provider is leaving the institution."},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "ENDED"
    assert r2.json()["data"]["endDate"] == "2026-12-31"


_ELIGIBLE_KWARGS = {"verification_status": "VERIFIED", "profile_status": "ACTIVE"}


async def _make_publication_eligible_provider(client, session_factory):
    headers, provider_id, user_id = await _provider_headers(session_factory, **_ELIGIBLE_KWARGS)

    from app.modules.identity.domain.models import Role, UserRole

    async with session_factory() as session:
        role = (await session.execute(__import__("sqlalchemy").select(Role).where(Role.code == "DOCTOR"))).scalar_one()
        session.add(UserRole(user_id=user_id, role_id=role.id, active=True))
        await session.commit()

    r = await client.get("/api/v1/providers/me", headers=headers)
    version = r.json()["data"]["version"]
    await client.patch(
        "/api/v1/providers/me",
        json={"professionalTitle": "Dr.", "biography": "Bio.", "yearsOfExperience": 5, "version": version},
        headers=headers,
    )
    await client.post(
        "/api/v1/providers/me/registrations",
        json={
            "registrationType": "MEDICAL_COUNCIL",
            "registrationNumber": f"OM-{provider_id}",
            "registrationAuthority": "Ordem dos Medicos",
            "registrationCountry": "MZ",
            "isPrimary": True,
        },
        headers=headers,
    )
    await client.post("/api/v1/providers/me/languages", json={"languageCode": "pt", "proficiency": "NATIVE"}, headers=headers)
    ref = await client.get("/api/v1/reference-data/provider-specialities?providerType=DOCTOR&active=true")
    non_qualification_speciality = next(s for s in ref.json()["data"] if not s["requiresVerifiedQualification"])
    await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": non_qualification_speciality["id"], "isPrimary": True}, headers=headers
    )
    svc = await client.post(
        "/api/v1/providers/me/services",
        json={
            "serviceCode": "CONSULT",
            "name": "Consultation",
            "durationMinutes": 30,
            "price": 100.0,
            "currency": "MZN",
            "deliveryModes": ["VIDEO"],
        },
        headers=headers,
    )
    service_id = svc.json()["data"]["id"]
    await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)

    upload = await client.post(
        "/api/v1/providers/me/media/profile-photo/upload-request",
        json={"fileName": "photo.jpg", "mimeType": "image/jpeg", "fileSize": 10240},
        headers=headers,
    )
    media_id = upload.json()["data"]["mediaId"]
    await client.post(
        f"/api/v1/providers/me/media/profile-photo/{media_id}/confirm", json={"checksum": "abc123"}, headers=headers
    )

    return headers, provider_id


async def test_publish_eligible_provider(client, session_factory):
    headers, provider_id = await _make_publication_eligible_provider(client, session_factory)
    r = await client.post("/api/v1/providers/me/publication/publish", json={"confirmPublicProfile": True}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["publicationStatus"] == "PUBLISHED"


async def test_publish_unverified_provider_rejected(client, session_factory):
    headers, _, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/publication/publish", json={}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_NOT_VERIFIED"


async def test_publish_incomplete_provider_reports_missing_requirements(client, session_factory):
    headers, _, user_id = await _provider_headers(session_factory, **_ELIGIBLE_KWARGS)

    from sqlalchemy import select

    from app.modules.identity.domain.models import Role, UserRole

    async with session_factory() as session:
        role = (await session.execute(select(Role).where(Role.code == "DOCTOR"))).scalar_one()
        session.add(UserRole(user_id=user_id, role_id=role.id, active=True))
        await session.commit()

    r = await client.post("/api/v1/providers/me/publication/publish", json={}, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_PROFILE_INCOMPLETE"
    assert len(r.json()["error"]["details"]["missingRequirements"]) > 0


async def test_unpublish_provider(client, session_factory):
    headers, provider_id = await _make_publication_eligible_provider(client, session_factory)
    await client.post("/api/v1/providers/me/publication/publish", json={}, headers=headers)

    r = await client.post("/api/v1/providers/me/publication/unpublish", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["publicationStatus"] == "UNPUBLISHED"


async def test_administrative_hide_requires_reason(client, session_factory):
    headers, provider_id = await _make_publication_eligible_provider(client, session_factory)
    await client.post("/api/v1/providers/me/publication/publish", json={}, headers=headers)

    bo_headers = await _backoffice_headers(session_factory)
    r = await client.post(f"/api/v1/back-office/providers/{provider_id}/hide", json={}, headers=bo_headers)
    assert r.status_code == 422, r.text

    r2 = await client.post(
        f"/api/v1/back-office/providers/{provider_id}/hide",
        json={"reasonCode": "PROFILE_UNDER_REVIEW", "comments": "Temporary hide pending review."},
        headers=bo_headers,
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["publicationStatus"] == "HIDDEN"
