#!/usr/bin/env python
"""Idempotently seeds a starter set of reference specialities
(`medical_specialities`) for the two provider types Identity can register
today — DOCTOR and NUTRITIONIST (spec section 12.1's reference-data list).
Safe to re-run — skips any `code` that already exists.

Usage:
    python -m scripts.seed_medical_specialities
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_session_factory  # noqa: E402
from app.modules.providers.domain.models import MedicalSpeciality  # noqa: E402

# (code, name, provider_type, requires_verified_qualification)
_SPECIALITIES: list[tuple[str, str, str, bool]] = [
    ("GENERAL_MEDICINE", "General Medicine", "DOCTOR", False),
    ("INTERNAL_MEDICINE", "Internal Medicine", "DOCTOR", True),
    ("CARDIOLOGY", "Cardiology", "DOCTOR", True),
    ("PAEDIATRICS", "Paediatrics", "DOCTOR", True),
    ("DERMATOLOGY", "Dermatology", "DOCTOR", True),
    ("OBSTETRICS_GYNAECOLOGY", "Obstetrics & Gynaecology", "DOCTOR", True),
    ("PSYCHIATRY", "Psychiatry", "DOCTOR", True),
    ("CLINICAL_NUTRITION", "Clinical Nutrition", "NUTRITIONIST", False),
    ("SPORTS_NUTRITION", "Sports Nutrition", "NUTRITIONIST", False),
    ("MATERNAL_CHILD_NUTRITION", "Maternal & Child Nutrition", "NUTRITIONIST", False),
    ("WEIGHT_MANAGEMENT", "Weight Management", "NUTRITIONIST", False),
]


async def seed() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = {s.code for s in (await session.execute(select(MedicalSpeciality))).scalars().all()}

        created = 0
        for code, name, provider_type, requires_verified_qualification in _SPECIALITIES:
            if code in existing:
                continue
            session.add(
                MedicalSpeciality(
                    code=code,
                    name=name,
                    provider_type=provider_type,
                    requires_verified_qualification=requires_verified_qualification,
                    active=True,
                )
            )
            created += 1
            print(f"+ speciality {code} ({provider_type})")

        await session.commit()
        print(f"Seed complete. {created} speciality(ies) added.")


if __name__ == "__main__":
    asyncio.run(seed())
