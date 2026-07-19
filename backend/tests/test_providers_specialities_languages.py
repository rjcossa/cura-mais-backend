"""Speciality and language management (spec 12, 13, 33.4, 37.5, 37.6)."""

from __future__ import annotations

from tests.conftest import PROVIDER_SELF_PERMISSIONS, auth_header, make_provider, make_user_with_role, token_for


async def _provider_headers(session_factory, **provider_kwargs):
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(session_factory, user_id, **provider_kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), provider_id


async def _speciality_id(client, provider_type: str) -> str:
    r = await client.get(f"/api/v1/reference-data/provider-specialities?providerType={provider_type}")
    assert r.status_code == 200, r.text
    return r.json()["data"][0]["id"]


async def test_list_reference_specialities_filters_by_type(client, session_factory):
    r = await client.get("/api/v1/reference-data/provider-specialities?providerType=NUTRITIONIST")
    assert r.status_code == 200, r.text
    assert all(s["providerType"] == "NUTRITIONIST" for s in r.json()["data"])
    assert len(r.json()["data"]) > 0


async def test_add_allowed_speciality(client, session_factory):
    headers, _ = await _provider_headers(session_factory, provider_type="DOCTOR")
    speciality_id = await _speciality_id(client, "DOCTOR")
    r = await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": speciality_id, "isPrimary": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["isPrimary"] is True


async def test_add_unsupported_speciality_for_provider_type_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory, provider_type="NUTRITIONIST")
    doctor_speciality_id = await _speciality_id(client, "DOCTOR")
    r = await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": doctor_speciality_id}, headers=headers
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_SPECIALITY_NOT_ALLOWED"


async def test_duplicate_speciality_assignment_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    speciality_id = await _speciality_id(client, "DOCTOR")
    await client.post("/api/v1/providers/me/specialities", json={"specialityId": speciality_id}, headers=headers)
    r = await client.post("/api/v1/providers/me/specialities", json={"specialityId": speciality_id}, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_SPECIALITY_ALREADY_ASSIGNED"


async def test_change_primary_speciality(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.get("/api/v1/reference-data/provider-specialities?providerType=DOCTOR")
    specialities = r.json()["data"]
    assert len(specialities) >= 2

    r1 = await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": specialities[0]["id"], "isPrimary": True}, headers=headers
    )
    first_assignment_id = r1.json()["data"]["id"]
    r2 = await client.post(
        "/api/v1/providers/me/specialities", json={"specialityId": specialities[1]["id"], "isPrimary": False}, headers=headers
    )
    second_assignment_id = r2.json()["data"]["id"]

    r3 = await client.post(f"/api/v1/providers/me/specialities/{second_assignment_id}/set-primary", headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["isPrimary"] is True

    r4 = await client.get("/api/v1/providers/me/specialities", headers=headers)
    by_id = {row["id"]: row for row in r4.json()["data"]}
    assert by_id[first_assignment_id]["isPrimary"] is False
    assert by_id[second_assignment_id]["isPrimary"] is True


async def test_add_language(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/languages", json={"languageCode": "pt-MZ", "proficiency": "FLUENT", "canConsult": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["proficiency"] == "FLUENT"


async def test_duplicate_language_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {"languageCode": "en", "proficiency": "NATIVE", "canConsult": True}
    await client.post("/api/v1/providers/me/languages", json=payload, headers=headers)
    r = await client.post("/api/v1/providers/me/languages", json=payload, headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_LANGUAGE_ALREADY_EXISTS"


async def test_invalid_language_code_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post(
        "/api/v1/providers/me/languages", json={"languageCode": "!!not-a-code!!", "proficiency": "BASIC"}, headers=headers
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_LANGUAGE_INVALID"


async def test_remove_last_language_succeeds_and_recalculates_completeness(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    await client.post("/api/v1/providers/me/languages", json={"languageCode": "pt", "proficiency": "NATIVE"}, headers=headers)

    r = await client.get("/api/v1/providers/me/completeness", headers=headers)
    assert "CONSULTATION_LANGUAGE" not in r.json()["data"]["missingRelationships"]

    r2 = await client.delete("/api/v1/providers/me/languages/pt", headers=headers)
    assert r2.status_code == 200, r2.text

    r3 = await client.get("/api/v1/providers/me/completeness", headers=headers)
    assert "CONSULTATION_LANGUAGE" in r3.json()["data"]["missingRelationships"]
