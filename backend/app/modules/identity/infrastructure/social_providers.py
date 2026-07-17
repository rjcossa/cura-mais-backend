"""Social identity provider adapters (spec sections 14.3, 20.4).

Each adapter validates the *provider's* token server-side — signature,
issuer, audience, expiry — and never trusts client-supplied profile data
as proof of identity (spec 14.3: "must never accept profile information
from the client as proof of provider identity"). Provider-specific
libraries/HTTP calls are confined to this file; the application layer only
ever sees a `SocialProviderResult`.
"""

from __future__ import annotations

from asyncio import to_thread
from dataclasses import dataclass
from typing import Protocol

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.modules.identity.domain.exceptions import IdentityError

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
FACEBOOK_GRAPH_URL = "https://graph.facebook.com/v19.0"


@dataclass(slots=True)
class SocialProviderResult:
    provider_subject: str
    email: str | None
    email_verified: bool
    display_name: str | None
    raw_metadata: dict


class SocialIdentityProvider(Protocol):
    async def validate_token(
        self, identity_token: str, *, nonce: str | None = None
    ) -> SocialProviderResult: ...


class GoogleIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def validate_token(
        self, identity_token: str, *, nonce: str | None = None
    ) -> SocialProviderResult:
        if not self._settings.google_client_id:
            raise IdentityError.for_code(
                "SOCIAL_TOKEN_INVALID", "Google sign-in is not configured on this server."
            )
        return await to_thread(self._verify_sync, identity_token, nonce)

    def _verify_sync(self, identity_token: str, nonce: str | None) -> SocialProviderResult:
        # Imported lazily so environments without network access to Google
        # (e.g. this sandbox) can still import the module for unit tests
        # that exercise the Mock provider instead.
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        try:
            claims = google_id_token.verify_oauth2_token(
                identity_token,
                google_requests.Request(),
                audience=self._settings.google_client_id,
            )
        except Exception as exc:  # google-auth raises several exception types
            raise IdentityError.for_code(
                "SOCIAL_TOKEN_INVALID", "The Google identity token could not be verified."
            ) from exc

        if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise IdentityError.for_code("SOCIAL_TOKEN_INVALID", "Unexpected token issuer.")
        if nonce is not None and claims.get("nonce") != nonce:
            raise IdentityError.for_code("SOCIAL_TOKEN_INVALID", "Nonce mismatch.")

        return SocialProviderResult(
            provider_subject=claims["sub"],
            email=claims.get("email"),
            email_verified=bool(claims.get("email_verified", False)),
            display_name=claims.get("name"),
            raw_metadata=claims,
        )


class AppleIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwk_client = PyJWKClient(APPLE_JWKS_URL)

    async def validate_token(
        self, identity_token: str, *, nonce: str | None = None
    ) -> SocialProviderResult:
        if not self._settings.apple_client_id:
            raise IdentityError.for_code(
                "SOCIAL_TOKEN_INVALID", "Apple sign-in is not configured on this server."
            )
        return await to_thread(self._verify_sync, identity_token, nonce)

    def _verify_sync(self, identity_token: str, nonce: str | None) -> SocialProviderResult:
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(identity_token)
            claims = jwt.decode(
                identity_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.apple_client_id,
                issuer=APPLE_ISSUER,
            )
        except jwt.PyJWTError as exc:
            raise IdentityError.for_code(
                "SOCIAL_TOKEN_INVALID", "The Apple identity token could not be verified."
            ) from exc

        if nonce is not None and claims.get("nonce") != nonce:
            raise IdentityError.for_code("SOCIAL_TOKEN_INVALID", "Nonce mismatch.")

        return SocialProviderResult(
            provider_subject=claims["sub"],
            email=claims.get("email"),
            email_verified=str(claims.get("email_verified", "false")).lower() == "true",
            display_name=None,  # Apple only sends name on first authorization, client-side.
            raw_metadata=claims,
        )


class FacebookIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def validate_token(
        self, identity_token: str, *, nonce: str | None = None
    ) -> SocialProviderResult:
        if not (self._settings.facebook_app_id and self._settings.facebook_app_secret):
            raise IdentityError.for_code(
                "SOCIAL_TOKEN_INVALID", "Facebook sign-in is not configured on this server."
            )

        app_token = f"{self._settings.facebook_app_id}|{self._settings.facebook_app_secret}"

        async with httpx.AsyncClient(base_url=FACEBOOK_GRAPH_URL, timeout=10) as client:
            debug_response = await client.get(
                "/debug_token",
                params={"input_token": identity_token, "access_token": app_token},
            )
            debug_response.raise_for_status()
            debug_data = debug_response.json().get("data", {})

            if not debug_data.get("is_valid") or debug_data.get("app_id") != self._settings.facebook_app_id:
                raise IdentityError.for_code(
                    "SOCIAL_TOKEN_INVALID", "The Facebook identity token could not be verified."
                )

            profile_response = await client.get(
                "/me", params={"fields": "id,email,name", "access_token": identity_token}
            )
            profile_response.raise_for_status()
            profile = profile_response.json()

        return SocialProviderResult(
            provider_subject=debug_data["user_id"],
            email=profile.get("email"),
            # Facebook does not expose an explicit "email_verified" claim;
            # an email is only ever returned for confirmed addresses.
            email_verified=bool(profile.get("email")),
            display_name=profile.get("name"),
            raw_metadata={"debug": debug_data, "profile": profile},
        )


class MockSocialIdentityProvider:
    """Deterministic provider for tests — configure `next_result` (or
    `next_error`) before calling `validate_token`.
    """

    def __init__(self) -> None:
        self.next_result: SocialProviderResult | None = None
        self.next_error: Exception | None = None
        self.calls: list[str] = []

    async def validate_token(
        self, identity_token: str, *, nonce: str | None = None
    ) -> SocialProviderResult:
        self.calls.append(identity_token)
        if self.next_error is not None:
            raise self.next_error
        if self.next_result is not None:
            return self.next_result
        raise IdentityError.for_code("SOCIAL_TOKEN_INVALID", "No mock result configured.")
