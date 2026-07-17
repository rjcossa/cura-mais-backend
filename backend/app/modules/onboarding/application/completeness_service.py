"""Application completeness calculation (spec section 8.3; unit test
requirements in 29.2). The single source of truth both the completeness
endpoint and submission validation call — see `application_service.py`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from app.modules.onboarding.application.requirements_service import RequirementsService
from app.modules.onboarding.application.section_definitions import (
    DOCUMENTS_SECTION_CODE,
    get_section_definitions,
)
from app.modules.onboarding.domain.models import OnboardingApplication
from app.modules.onboarding.domain.repositories import ApplicationDocumentRepository, ApplicationRepository


@dataclass(slots=True)
class CompletenessResult:
    complete: bool
    completion_percentage: int
    missing_fields: list[dict] = field(default_factory=list)
    missing_documents: list[dict] = field(default_factory=list)
    invalid_documents: list[dict] = field(default_factory=list)
    expired_documents: list[dict] = field(default_factory=list)
    processing_documents: list[dict] = field(default_factory=list)


class CompletenessService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        document_repo: ApplicationDocumentRepository,
        requirements_service: RequirementsService,
    ) -> None:
        self._applications = application_repo
        self._documents = document_repo
        self._requirements = requirements_service

    async def calculate(self, application: OnboardingApplication) -> CompletenessResult:
        section_defs = get_section_definitions(application.applicant_type)
        sections = {s.section_code: s for s in await self._applications.list_sections(application.id)}

        professional_registration = sections.get("PROFESSIONAL_REGISTRATION")
        professional_registration_data = (
            professional_registration.data if professional_registration else None
        )

        missing_fields: list[dict] = []
        mandatory_sections = 0
        complete_sections = 0

        for definition in section_defs:
            if definition.code == DOCUMENTS_SECTION_CODE:
                continue  # handled via document requirements below
            mandatory_sections += 1
            row = sections.get(definition.code)
            status = row.status if row else "NOT_STARTED"
            if status == "COMPLETE":
                complete_sections += 1
            elif row and row.validation_errors:
                for err in row.validation_errors:
                    missing_fields.append({"section": definition.code, "field": err.get("field")})
            elif not row:
                for f in definition.required_fields:
                    missing_fields.append({"section": definition.code, "field": f})

        documents = await self._documents.list_current(application.id)
        by_type: dict[str, list] = {}
        for doc in documents:
            by_type.setdefault(doc.document_type, []).append(doc)

        resolved_requirements = await self._requirements.resolve_documents(
            application, professional_registration_data
        )
        today = datetime.date.today()

        missing_documents: list[dict] = []
        invalid_documents: list[dict] = []
        expired_documents: list[dict] = []
        processing_documents: list[dict] = []
        mandatory_documents = 0
        satisfied_documents = 0

        for req in resolved_requirements:
            if not req.mandatory:
                continue
            mandatory_documents += 1
            docs_of_type = by_type.get(req.document_type, [])
            if not docs_of_type:
                missing_documents.append({"documentType": req.document_type})
                continue

            doc = docs_of_type[0]
            if doc.review_status == "REJECTED":
                invalid_documents.append({"documentType": req.document_type})
            elif req.requires_expiry_date and doc.expiry_date and doc.expiry_date < today:
                expired_documents.append({"documentType": req.document_type})
            elif doc.processing_status in {"PENDING_UPLOAD", "UPLOADED", "PROCESSING"}:
                processing_documents.append({"documentType": req.document_type})
            elif doc.processing_status == "AVAILABLE" and doc.review_status in {"PENDING", "ACCEPTED"}:
                satisfied_documents += 1
            else:
                invalid_documents.append({"documentType": req.document_type})

        total_mandatory = mandatory_sections + mandatory_documents
        total_complete = complete_sections + satisfied_documents
        percentage = 100 if total_mandatory == 0 else round(100 * total_complete / total_mandatory)

        complete = (
            not missing_fields
            and not missing_documents
            and not invalid_documents
            and not expired_documents
            and not processing_documents
        )

        return CompletenessResult(
            complete=complete,
            completion_percentage=percentage,
            missing_fields=missing_fields,
            missing_documents=missing_documents,
            invalid_documents=invalid_documents,
            expired_documents=expired_documents,
            processing_documents=processing_documents,
        )
