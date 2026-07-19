"""Consultation language management (spec section 13, 37.6).

`provider_languages` has no `version`/`deleted_at` column (spec 30.6's
DDL, and absent from spec 35's optimistic-locking list) — removal is a
real hard delete, not a soft one, unlike every other provider-owned
aggregate here.
"""

from __future__ import annotations

import re
import uuid

from app.modules.providers.application.completeness_service import CompletenessService
from app.modules.providers.domain.enums import LanguageProficiency
from app.modules.providers.domain.events import ProviderEvent
from app.modules.providers.domain.exceptions import ProviderError
from app.modules.providers.domain.models import Provider, ProviderLanguage
from app.modules.providers.domain.repositories import LanguageRepository, OutboxRepository

_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


class LanguageService:
    def __init__(self, language_repo: LanguageRepository, completeness_service: CompletenessService, outbox_repo: OutboxRepository) -> None:
        self._languages = language_repo
        self._completeness = completeness_service
        self._outbox = outbox_repo

    async def list_for_provider(self, provider_id: uuid.UUID) -> list[ProviderLanguage]:
        return await self._languages.list_for_provider(provider_id)

    async def get_owned(self, provider_id: uuid.UUID, language_code: str) -> ProviderLanguage:
        language = await self._languages.get(provider_id, language_code)
        if language is None:
            raise ProviderError.for_code("PROVIDER_LANGUAGE_NOT_FOUND")
        return language

    async def add_language(
        self, provider: Provider, *, language_code: str, proficiency: str, can_consult: bool
    ) -> ProviderLanguage:
        if not _LANGUAGE_CODE_RE.match(language_code):
            raise ProviderError.for_code("PROVIDER_LANGUAGE_INVALID", "Unsupported language code format.")
        if proficiency not in {p.value for p in LanguageProficiency}:
            raise ProviderError.for_code("PROVIDER_LANGUAGE_INVALID", "Unsupported proficiency level.")
        if await self._languages.get(provider.id, language_code) is not None:
            raise ProviderError.for_code("PROVIDER_LANGUAGE_ALREADY_EXISTS")

        language = ProviderLanguage(
            provider_id=provider.id, language_code=language_code, proficiency=proficiency, can_consult=can_consult
        )
        await self._languages.add(language)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.LANGUAGE_ADDED,
            {"providerId": str(provider.id), "languageCode": language_code},
            aggregate_id=provider.id,
        )
        return language

    async def update_language(
        self, provider: Provider, language: ProviderLanguage, *, proficiency: str | None, can_consult: bool | None
    ) -> ProviderLanguage:
        if proficiency is not None:
            if proficiency not in {p.value for p in LanguageProficiency}:
                raise ProviderError.for_code("PROVIDER_LANGUAGE_INVALID", "Unsupported proficiency level.")
            language.proficiency = proficiency
        if can_consult is not None:
            language.can_consult = can_consult
        await self._completeness.refresh(provider)
        return language

    async def remove_language(self, provider: Provider, language: ProviderLanguage) -> None:
        language_code = language.language_code
        await self._languages.delete(language)
        await self._completeness.refresh(provider)

        await self._outbox.enqueue(
            ProviderEvent.LANGUAGE_REMOVED,
            {"providerId": str(provider.id), "languageCode": language_code},
            aggregate_id=provider.id,
        )
