#!/usr/bin/env python
"""Idempotently seeds the initial document-requirement rules (spec
sections 10.1-10.5) into `onboarding_document_requirements`. Safe to
re-run — skips any (applicant_type, document_type) pair that already
exists.

Usage:
    python -m scripts.seed_document_requirements
"""

from __future__ import annotations

import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_session_factory  # noqa: E402
from app.modules.onboarding.domain.models import OnboardingDocumentRequirement  # noqa: E402

_PDF_JPEG_PNG = ["application/pdf", "image/jpeg", "image/png"]
_IMAGE_ONLY = ["image/jpeg", "image/png"]
_PDF_ONLY = ["application/pdf"]
_10MB = 10 * 1024 * 1024

# Document types that plausibly carry issue/expiry dates, a document
# number, and an issuing authority (licences, certificates, official ID).
# Applied uniformly below rather than per-document-type for brevity — spec
# section 10.5 lists these as configurable per-rule attributes, so this is
# a starting default a back-office admin (ONBOARDING_RULE_MANAGE) can
# refine per document type later.
_LICENCE_LIKE = {
    "NATIONAL_ID",
    "MEDICAL_COUNCIL_CERTIFICATE",
    "PROFESSIONAL_LICENCE",
    "SPECIALISATION_CERTIFICATE",
    "PROFESSIONAL_INDEMNITY_CERTIFICATE",
    "PROFESSIONAL_REGISTRATION_CERTIFICATE",
    "OPERATING_LICENCE",
    "HEALTH_FACILITY_LICENCE",
    "PHARMACY_OPERATING_LICENCE",
    "PHARMACY_REGULATORY_CERTIFICATE",
    "RESPONSIBLE_PHARMACIST_CERTIFICATE",
}

# (applicant_type, [document_type, ...]) — spec sections 10.1-10.4.
_DOCUMENT_LISTS: dict[str, list[str]] = {
    "DOCTOR": [
        "NATIONAL_ID",
        "MEDICAL_COUNCIL_CERTIFICATE",
        "GRADUATION_CERTIFICATE",
        "CURRICULUM_VITAE",
        "PROFILE_PHOTO",
        "PROFESSIONAL_LICENCE",
        "SPECIALISATION_CERTIFICATE",
        "PROFESSIONAL_INDEMNITY_CERTIFICATE",
        "OTHER_SUPPORTING_DOCUMENT",
    ],
    "NUTRITIONIST": [
        "NATIONAL_ID",
        "GRADUATION_CERTIFICATE",
        "PROFESSIONAL_REGISTRATION_CERTIFICATE",
        "CURRICULUM_VITAE",
        "PROFILE_PHOTO",
        "SPECIALISATION_CERTIFICATE",
        "OTHER_SUPPORTING_DOCUMENT",
    ],
    "HOSPITAL": [
        "CERTIFICATE_OF_INCORPORATION",
        "OPERATING_LICENCE",
        "HEALTH_FACILITY_LICENCE",
        "TAX_REGISTRATION_CERTIFICATE",
        "PROOF_OF_ADDRESS",
        "DIRECTOR_IDENTIFICATION",
        "AUTHORISED_REPRESENTATIVE_DOCUMENT",
        "OWNERSHIP_INFORMATION",
        "BANK_ACCOUNT_PROOF",
        "PROFESSIONAL_INDEMNITY_CERTIFICATE",
        "OTHER_SUPPORTING_DOCUMENT",
    ],
    "PHARMACY": [
        "CERTIFICATE_OF_INCORPORATION",
        "PHARMACY_OPERATING_LICENCE",
        "PHARMACY_REGULATORY_CERTIFICATE",
        "RESPONSIBLE_PHARMACIST_CERTIFICATE",
        "TAX_REGISTRATION_CERTIFICATE",
        "PROOF_OF_ADDRESS",
        "DIRECTOR_IDENTIFICATION",
        "AUTHORISED_REPRESENTATIVE_DOCUMENT",
        "BANK_ACCOUNT_PROOF",
        "OTHER_SUPPORTING_DOCUMENT",
    ],
}
# Clinic uses the same document set as Hospital (spec 10.3 covers both
# under one heading: "Hospital and Clinic Requirements").
_DOCUMENT_LISTS["CLINIC"] = _DOCUMENT_LISTS["HOSPITAL"]

# SPECIALISATION_CERTIFICATE is seeded as non-mandatory by default;
# `RequirementsService` (application layer) conditionally treats it as
# mandatory for a given application once the applicant has selected a
# speciality in their professional-registration section — see that
# service's docstring for why this one rule isn't purely config-driven
# (spec 29.2's "Conditional Requirement" test; spec 5.4's "driven by
# configuration where practical").
_NOT_MANDATORY_BY_DEFAULT = {"OTHER_SUPPORTING_DOCUMENT", "SPECIALISATION_CERTIFICATE"}

_EFFECTIVE_FROM = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


async def seed() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = {
            (r.applicant_type, r.document_type)
            for r in (await session.execute(select(OnboardingDocumentRequirement))).scalars().all()
        }

        created = 0
        for applicant_type, document_types in _DOCUMENT_LISTS.items():
            for document_type in document_types:
                if (applicant_type, document_type) in existing:
                    continue

                is_licence_like = document_type in _LICENCE_LIKE
                mime_types = (
                    _IMAGE_ONLY
                    if document_type == "PROFILE_PHOTO"
                    else _PDF_ONLY
                    if document_type == "MEDICAL_COUNCIL_CERTIFICATE"
                    else _PDF_JPEG_PNG
                )

                session.add(
                    OnboardingDocumentRequirement(
                        applicant_type=applicant_type,
                        application_purpose=None,  # applies to every purpose unless overridden
                        country_code=None,
                        speciality_code=None,
                        document_type=document_type,
                        mandatory=document_type not in _NOT_MANDATORY_BY_DEFAULT,
                        minimum_quantity=1,
                        maximum_quantity=1,
                        requires_issue_date=is_licence_like,
                        requires_expiry_date=is_licence_like,
                        requires_document_number=is_licence_like,
                        requires_issuing_authority=is_licence_like,
                        allowed_mime_types=mime_types,
                        maximum_file_size_bytes=_10MB,
                        effective_from=_EFFECTIVE_FROM,
                        effective_until=None,
                        active=True,
                    )
                )
                created += 1
                print(f"+ {applicant_type} requires {document_type}")

        await session.commit()
        print(f"Seed complete. {created} requirement(s) added.")


if __name__ == "__main__":
    asyncio.run(seed())
