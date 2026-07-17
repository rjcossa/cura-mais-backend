"""Resolves which sections and documents are required for a given
application (spec sections 7.1 step 6-7, 8.2, 10). Used by the
requirements endpoint, completeness calculation, and submission
validation, so all three always agree on what's actually required.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.onboarding.application.section_definitions import (
    SectionDefinition,
    get_section_definitions,
)
from app.modules.onboarding.domain.models import OnboardingApplication, OnboardingDocumentRequirement
from app.modules.onboarding.domain.repositories import DocumentRequirementRepository


@dataclass(slots=True)
class ResolvedDocumentRequirement:
    requirement_id: object
    document_type: str
    mandatory: bool
    requires_issue_date: bool
    requires_expiry_date: bool
    requires_document_number: bool
    requires_issuing_authority: bool
    allowed_mime_types: list[str]
    maximum_file_size_bytes: int


class RequirementsService:
    def __init__(self, document_requirement_repo: DocumentRequirementRepository) -> None:
        self._document_requirements = document_requirement_repo

    def resolve_sections(self, applicant_type: str) -> tuple[SectionDefinition, ...]:
        return get_section_definitions(applicant_type)

    async def resolve_documents(
        self, application: OnboardingApplication, professional_registration_data: dict | None = None
    ) -> list[ResolvedDocumentRequirement]:
        rows = await self._document_requirements.list_applicable(
            application.applicant_type, application.application_purpose, None
        )

        has_speciality = bool((professional_registration_data or {}).get("speciality"))

        resolved = []
        for row in rows:
            mandatory = row.mandatory
            if row.document_type == "SPECIALISATION_CERTIFICATE":
                # Conditional rule (spec 29.2): only mandatory once the
                # applicant has actually selected a speciality.
                mandatory = has_speciality
            resolved.append(_to_resolved(row, mandatory))
        return resolved


def _to_resolved(row: OnboardingDocumentRequirement, mandatory: bool) -> ResolvedDocumentRequirement:
    return ResolvedDocumentRequirement(
        requirement_id=row.id,
        document_type=row.document_type,
        mandatory=mandatory,
        requires_issue_date=row.requires_issue_date,
        requires_expiry_date=row.requires_expiry_date,
        requires_document_number=row.requires_document_number,
        requires_issuing_authority=row.requires_issuing_authority,
        allowed_mime_types=list(row.allowed_mime_types or []),
        maximum_file_size_bytes=row.maximum_file_size_bytes,
    )
