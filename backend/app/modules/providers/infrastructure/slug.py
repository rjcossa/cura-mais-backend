"""Public slug generation (spec section 8.1: "Generate a unique public
slug", section 37.1's "Slug Collision" test). No new dependency — accent
stripping uses the stdlib `unicodedata` rather than pulling in
`python-slugify`/`unidecode` for something this small.
"""

from __future__ import annotations

import re
import unicodedata

from app.modules.providers.domain.repositories import ProviderRepository


def slugify(*parts: str | None) -> str:
    text = " ".join(p for p in parts if p)
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return hyphenated or "provider"


async def generate_unique_slug(
    repo: ProviderRepository, first_name: str, last_name: str, professional_title: str | None = None
) -> str:
    base = slugify(professional_title, first_name, last_name)
    candidate = base
    suffix = 2
    while await repo.slug_exists(candidate):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
