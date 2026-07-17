"""FastAPI dependency wiring for the Onboarding module. Same rationale as
`app.modules.identity.api.deps`: each factory builds a fresh set of
repositories bound to the current request's `AsyncSession`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.identity.api.deps import CurrentAuth
from app.modules.identity.application.identity_ports import IdentityCommandService, IdentityQueryService
from app.modules.identity.infrastructure.repositories import SqlAlchemyOutboxRepository as IdentityOutboxRepo
from app.modules.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemySecurityLogRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyUserRepository,
)
from app.modules.onboarding.application.application_service import ApplicationService
from app.modules.onboarding.application.assignment_service import AssignmentService
from app.modules.onboarding.application.completeness_service import CompletenessService
from app.modules.onboarding.application.decision_service import DecisionService
from app.modules.onboarding.application.document_service import DocumentService
from app.modules.onboarding.application.information_request_service import InformationRequestService
from app.modules.onboarding.application.requirements_service import RequirementsService
from app.modules.onboarding.application.review_service import ReviewService
from app.modules.onboarding.application.risk_flag_service import RiskFlagService
from app.modules.onboarding.application.verification_service import VerificationService
from app.modules.onboarding.infrastructure.identity_adapter import IdentityAdapter
from app.modules.onboarding.infrastructure.repositories import (
    SqlAlchemyApplicationDocumentRepository,
    SqlAlchemyApplicationRepository,
    SqlAlchemyAssignmentRepository,
    SqlAlchemyDecisionRepository,
    SqlAlchemyDocumentRequirementRepository,
    SqlAlchemyInformationRequestRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyReverificationRepository,
    SqlAlchemyReviewRepository,
    SqlAlchemyRiskFlagRepository,
    SqlAlchemyVerificationCheckRepository,
)
from app.shared.documents.port import get_document_adapter

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _repos(db: AsyncSession):
    return {
        "application": SqlAlchemyApplicationRepository(db),
        "document_requirement": SqlAlchemyDocumentRequirementRepository(db),
        "document": SqlAlchemyApplicationDocumentRepository(db),
        "assignment": SqlAlchemyAssignmentRepository(db),
        "review": SqlAlchemyReviewRepository(db),
        "verification": SqlAlchemyVerificationCheckRepository(db),
        "information_request": SqlAlchemyInformationRequestRepository(db),
        "decision": SqlAlchemyDecisionRepository(db),
        "risk_flag": SqlAlchemyRiskFlagRepository(db),
        "reverification": SqlAlchemyReverificationRepository(db),
        "outbox": SqlAlchemyOutboxRepository(db),
    }


def _identity_adapter(db: AsyncSession) -> IdentityAdapter:
    query = IdentityQueryService(SqlAlchemyUserRepository(db), SqlAlchemyRoleRepository(db))
    role_service = _identity_role_service(db)
    command = IdentityCommandService(role_service)
    return IdentityAdapter(query, command)


def _identity_role_service(db: AsyncSession):
    from app.modules.identity.application.role_service import RoleService

    return RoleService(
        SqlAlchemyUserRepository(db),
        SqlAlchemyRoleRepository(db),
        SqlAlchemySessionRepository(db),
        SqlAlchemySecurityLogRepository(db),
        IdentityOutboxRepo(db),
    )


def get_requirements_service(db: DbSession) -> RequirementsService:
    return RequirementsService(_repos(db)["document_requirement"])


def get_completeness_service(db: DbSession) -> CompletenessService:
    r = _repos(db)
    return CompletenessService(r["application"], r["document"], get_requirements_service(db))


def get_application_service(db: DbSession) -> ApplicationService:
    r = _repos(db)
    return ApplicationService(
        r["application"], get_requirements_service(db), get_completeness_service(db), r["outbox"], _identity_adapter(db)
    )


def get_document_service(db: DbSession) -> DocumentService:
    r = _repos(db)
    return DocumentService(r["document"], get_requirements_service(db), get_document_adapter())


def get_assignment_service(db: DbSession) -> AssignmentService:
    r = _repos(db)
    return AssignmentService(r["application"], r["assignment"], r["outbox"], _identity_adapter(db))


def get_review_service(db: DbSession) -> ReviewService:
    r = _repos(db)
    return ReviewService(r["application"], r["review"], r["document"], r["assignment"], r["risk_flag"], r["outbox"])


def get_verification_service(db: DbSession) -> VerificationService:
    r = _repos(db)
    return VerificationService(r["verification"], r["outbox"])


def get_information_request_service(db: DbSession) -> InformationRequestService:
    r = _repos(db)
    return InformationRequestService(r["application"], r["information_request"], r["outbox"])


def get_risk_flag_service(db: DbSession) -> RiskFlagService:
    r = _repos(db)
    return RiskFlagService(r["risk_flag"], r["outbox"])


def get_decision_service(db: DbSession) -> DecisionService:
    r = _repos(db)
    return DecisionService(
        r["application"],
        r["decision"],
        r["review"],
        r["document"],
        r["risk_flag"],
        r["outbox"],
        _identity_adapter(db),
        get_verification_service(db),
    )


def get_application_repo(db: DbSession):
    return _repos(db)["application"]


def get_assignment_repo(db: DbSession):
    return _repos(db)["assignment"]


def get_review_repo(db: DbSession):
    return _repos(db)["review"]


def get_document_repo(db: DbSession):
    return _repos(db)["document"]


def get_verification_repo(db: DbSession):
    return _repos(db)["verification"]


def get_information_request_repo(db: DbSession):
    return _repos(db)["information_request"]


def get_decision_repo(db: DbSession):
    return _repos(db)["decision"]


def get_risk_flag_repo(db: DbSession):
    return _repos(db)["risk_flag"]


__all__ = [
    "CurrentAuth",
    "DbSession",
    "get_application_repo",
    "get_application_service",
    "get_assignment_repo",
    "get_assignment_service",
    "get_completeness_service",
    "get_decision_repo",
    "get_decision_service",
    "get_document_repo",
    "get_document_service",
    "get_information_request_repo",
    "get_information_request_service",
    "get_requirements_service",
    "get_review_repo",
    "get_review_service",
    "get_risk_flag_repo",
    "get_risk_flag_service",
    "get_verification_repo",
    "get_verification_service",
]
