"""Provider service and location management (spec 14, 15, 16, 33.5, 33.6,
37.7, 37.8)."""

from __future__ import annotations

from tests.conftest import PROVIDER_SELF_PERMISSIONS, auth_header, make_provider, make_user_with_role, token_for


async def _provider_headers(session_factory, **provider_kwargs):
    kwargs = {"verification_status": "VERIFIED", "profile_status": "ACTIVE", **provider_kwargs}
    user_id = await make_user_with_role(session_factory, "PATIENT")
    provider_id = await make_provider(session_factory, user_id, **kwargs)
    token = await token_for(user_id, ["PATIENT"], PROVIDER_SELF_PERMISSIONS)
    return auth_header(token), provider_id


_PAID_SERVICE = {
    "serviceCode": "GENERAL_CONSULTATION",
    "name": "General Medical Consultation",
    "durationMinutes": 30,
    "price": 1500.0,
    "currency": "MZN",
    "proBono": False,
    "deliveryModes": ["VIDEO"],
}


async def test_create_paid_service_starts_draft(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/services", json=_PAID_SERVICE, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["status"] == "DRAFT"
    assert data["deliveryModes"] == ["VIDEO"]


async def test_create_pro_bono_service_allows_zero_price(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_PAID_SERVICE, "serviceCode": "PRO_BONO_CHECKUP", "proBono": True, "price": None, "currency": None}
    r = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["proBono"] is True


async def test_activate_service_missing_delivery_mode_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_PAID_SERVICE, "serviceCode": "NO_MODE", "deliveryModes": []}
    r = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    service_id = r.json()["data"]["id"]

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)
    assert r2.status_code == 422, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_SERVICE_DELIVERY_MODE_REQUIRED"


async def test_activate_valid_video_service(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/services", json=_PAID_SERVICE, headers=headers)
    service_id = r.json()["data"]["id"]

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "ACTIVE"


async def test_activate_in_person_service_without_location_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_PAID_SERVICE, "serviceCode": "IN_PERSON_VISIT", "deliveryModes": ["IN_PERSON"]}
    r = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    service_id = r.json()["data"]["id"]

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)
    assert r2.status_code == 422, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_SERVICE_LOCATION_REQUIRED"


async def test_activate_service_for_suspended_provider_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory, profile_status="SUSPENDED")
    r = await client.post("/api/v1/providers/me/services", json=_PAID_SERVICE, headers=headers)
    service_id = r.json()["data"]["id"]

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_SUSPENDED"


async def test_negative_price_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_PAID_SERVICE, "serviceCode": "NEG_PRICE", "price": -5}
    r = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_SERVICE_PRICE_INVALID"


async def test_paid_service_without_currency_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_PAID_SERVICE, "serviceCode": "NO_CURRENCY", "currency": None}
    r = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_SERVICE_PRICE_INVALID"


async def test_deactivate_service(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/services", json=_PAID_SERVICE, headers=headers)
    service_id = r.json()["data"]["id"]
    await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/deactivate", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "INACTIVE"


async def test_archive_service_with_history_is_no_longer_active(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/services", json=_PAID_SERVICE, headers=headers)
    service_id = r.json()["data"]["id"]
    await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)

    r2 = await client.post(f"/api/v1/providers/me/services/{service_id}/archive", headers=headers)
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "ARCHIVED"

    r3 = await client.get("/api/v1/providers/me/services?status=ACTIVE", headers=headers)
    assert service_id not in [s["id"] for s in r3.json()["data"]]


_LOCATION_PAYLOAD = {
    "locationType": "PRIVATE_PRACTICE",
    "name": "Paulo Mucavele Medical Practice",
    "addressLine1": "Avenida Julius Nyerere",
    "city": "Maputo",
    "province": "Maputo Cidade",
    "countryCode": "MZ",
    "latitude": -25.9692,
    "longitude": 32.5732,
    "isPrimary": True,
}


async def test_add_valid_physical_location(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/locations", json=_LOCATION_PAYLOAD, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["isPrimary"] is True


async def test_virtual_location_strips_physical_address(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_LOCATION_PAYLOAD, "locationType": "VIRTUAL", "isPrimary": False}
    r = await client.post("/api/v1/providers/me/locations", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["addressLine1"] is None
    assert data["city"] is None


async def test_invalid_latitude_rejected(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    payload = {**_LOCATION_PAYLOAD, "latitude": 999.0}
    r = await client.post("/api/v1/providers/me/locations", json=payload, headers=headers)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "PROVIDER_LOCATION_INVALID"


async def test_set_new_primary_location_clears_previous(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    r1 = await client.post("/api/v1/providers/me/locations", json=_LOCATION_PAYLOAD, headers=headers)
    first_id = r1.json()["data"]["id"]

    second = {**_LOCATION_PAYLOAD, "name": "Second practice", "isPrimary": False}
    r2 = await client.post("/api/v1/providers/me/locations", json=second, headers=headers)
    second_id = r2.json()["data"]["id"]

    r3 = await client.post(f"/api/v1/providers/me/locations/{second_id}/set-primary", headers=headers)
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["isPrimary"] is True

    r4 = await client.get("/api/v1/providers/me/locations", headers=headers)
    by_id = {row["id"]: row for row in r4.json()["data"]}
    assert by_id[first_id]["isPrimary"] is False
    assert by_id[second_id]["isPrimary"] is True


async def test_deactivate_only_physical_location_used_by_active_service_blocked(client, session_factory):
    headers, _ = await _provider_headers(session_factory)
    loc = await client.post("/api/v1/providers/me/locations", json=_LOCATION_PAYLOAD, headers=headers)
    location_id = loc.json()["data"]["id"]

    payload = {**_PAID_SERVICE, "serviceCode": "IN_PERSON_2", "deliveryModes": ["IN_PERSON"]}
    svc = await client.post("/api/v1/providers/me/services", json=payload, headers=headers)
    service_id = svc.json()["data"]["id"]
    await client.post(f"/api/v1/providers/me/services/{service_id}/activate", headers=headers)

    r = await client.post(f"/api/v1/providers/me/locations/{location_id}/deactivate", headers=headers)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "PROVIDER_LOCATION_IN_USE"


async def test_edit_institution_owned_location_rejected(client, session_factory):
    headers, provider_id = await _provider_headers(session_factory)
    r = await client.post("/api/v1/providers/me/locations", json={**_LOCATION_PAYLOAD, "isPrimary": False}, headers=headers)
    location_id = r.json()["data"]["id"]

    from app.modules.providers.domain.models import ProviderLocation

    async with session_factory() as session:
        row = await session.get(ProviderLocation, location_id)
        row.institution_id = provider_id  # any non-null uuid marks it institution-owned
        await session.commit()

    r2 = await client.patch(f"/api/v1/providers/me/locations/{location_id}", json={"name": "New name"}, headers=headers)
    assert r2.status_code == 403, r2.text
    assert r2.json()["error"]["code"] == "PROVIDER_INSTITUTION_LOCATION_NOT_EDITABLE"
