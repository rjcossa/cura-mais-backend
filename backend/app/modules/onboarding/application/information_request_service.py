"""Information requests: create / respond / resubmit / overdue handling
(spec section 15).
"""

from __future__ import annotations

import datetime
import uuid

from app.modules.onboarding.application import status_helper
from app.modules.onboarding.domain.enums import ApplicationStatus
from app.modules.onboarding.domain.events import OnboardingEvent, OnboardingNotification
from app.modules.onboarding.domain.exceptions import OnboardingError
from app.modules.onboarding.domain.models import (
    OnboardingApplication,
    OnboardingInformationRequest,
    OnboardingInformationRequestItem,
)
from app.modules.onboarding.domain.repositories import (
    ApplicationRepository,
    InformationRequestRepository,
    OutboxRepository,
)


class InformationRequestService:
    def __init__(
        self,
        application_repo: ApplicationRepository,
        request_repo: InformationRequestRepository,
        outbox_repo: OutboxRepository,
    ) -> None:
        self._applications = application_repo
        self._requests = request_repo
        self._outbox = outbox_repo

    async def create_request(
        self,
        application: OnboardingApplication,
        *,
        reason_code: str,
        message: str,
        response_due_date: datetime.date | None,
        items: list[dict],
        requested_by: uuid.UUID,
    ) -> OnboardingInformationRequest:
        request = OnboardingInformationRequest(
            application_id=application.id,
            requested_by=requested_by,
            reason_code=reason_code,
            message=message,
            status="OPEN",
            response_due_date=response_due_date,
        )
        await self._requests.add(request)

        for item in items:
            await self._requests.add_item(
                OnboardingInformationRequestItem(
                    information_request_id=request.id,
                    item_type=item["item_type"],
                    document_type=item.get("document_type"),
                    field_name=item.get("field_name"),
                    instruction=item["instruction"],
                    status="OPEN",
                )
            )

        if application.status in {
            ApplicationStatus.UNDER_REVIEW.value,
            ApplicationStatus.PENDING_SECOND_LEVEL_REVIEW.value,
            ApplicationStatus.PENDING_APPROVAL.value,
        }:
            # Pause the SLA clock (spec 15.1 step 6) — we track paused time
            # as a marker timestamp; total_paused_seconds is accumulated
            # when the pause ends (resubmission), see resubmit-adjacent
            # logic in ApplicationService/status_helper callers.
            application.service_level_paused_at = datetime.datetime.now(datetime.UTC)
            await status_helper.transition(
                application,
                ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED,
                self._applications,
                changed_by=requested_by,
                reason_code=reason_code,
                comments=message,
            )

        await self._outbox.enqueue(
            OnboardingEvent.INFORMATION_REQUESTED,
            {
                "applicationId": str(application.id),
                "requestId": str(request.id),
                "notificationCommand": OnboardingNotification.INFORMATION_REQUESTED,
                "channel": "EMAIL",
                "parameters": {"reasonCode": reason_code, "message": message},
            },
            aggregate_id=application.id,
        )
        return request

    async def respond(
        self,
        application: OnboardingApplication,
        request: OnboardingInformationRequest,
        *,
        message: str | None,
        document_ids: list[uuid.UUID],
        updated_fields: list[str],
        responded_by: uuid.UUID,
    ) -> OnboardingInformationRequest:
        if request.status in {"CLOSED", "CANCELLED", "SATISFIED"}:
            raise OnboardingError.for_code("ONBOARDING_INFORMATION_REQUEST_CLOSED")

        items = await self._requests.list_items(request.id)
        # Mark items satisfied when the response references them: document
        # items are satisfied by an attached document id being present at
        # all (detailed matching to a *specific* document type is done by
        # the caller/route, which knows which document was just uploaded);
        # field items are satisfied when their field name appears in
        # `updated_fields`.
        any_satisfied = False
        for item in items:
            if item.status in {"SATISFIED"}:
                continue
            if item.item_type == "DOCUMENT" and document_ids:
                item.status = "SATISFIED"
                item.satisfied_by = responded_by
                item.satisfied_at = datetime.datetime.now(datetime.UTC)
                any_satisfied = True
            elif item.item_type == "FIELD" and item.field_name in updated_fields:
                item.status = "SATISFIED"
                item.satisfied_by = responded_by
                item.satisfied_at = datetime.datetime.now(datetime.UTC)
                any_satisfied = True
            elif item.item_type in {"DECLARATION", "EXPLANATION", "OTHER"} and message:
                item.status = "RESPONDED"

        remaining_open = [i for i in items if i.status == "OPEN"]
        request.responded_at = datetime.datetime.now(datetime.UTC)
        if not remaining_open:
            request.status = "SATISFIED"
            request.satisfied_at = request.responded_at
        elif any_satisfied:
            request.status = "PARTIALLY_RESPONDED"
        else:
            request.status = "RESPONDED"

        await self._outbox.enqueue(
            OnboardingEvent.INFORMATION_RESPONDED,
            {"applicationId": str(application.id), "requestId": str(request.id)},
            aggregate_id=application.id,
        )
        return request

    async def resubmit(
        self,
        application: OnboardingApplication,
        request: OnboardingInformationRequest,
        *,
        resubmitted_by: uuid.UUID,
    ) -> None:
        if application.status != ApplicationStatus.ADDITIONAL_INFORMATION_REQUIRED.value:
            raise OnboardingError.for_code("ONBOARDING_APPLICATION_STATE_INVALID")

        items = await self._requests.list_items(request.id)
        mandatory_open = [i for i in items if i.status == "OPEN"]
        if mandatory_open:
            raise OnboardingError.for_code(
                "ONBOARDING_INFORMATION_REQUEST_INCOMPLETE",
                details={"openItems": [i.id.hex for i in mandatory_open]},
            )

        request.status = "CLOSED"
        request.closed_at = datetime.datetime.now(datetime.UTC)

        if application.service_level_paused_at is not None:
            paused_seconds = int(
                (datetime.datetime.now(datetime.UTC) - application.service_level_paused_at).total_seconds()
            )
            application.total_paused_seconds += max(paused_seconds, 0)
            application.service_level_paused_at = None

        await status_helper.transition(
            application, ApplicationStatus.RESUBMITTED, self._applications, changed_by=resubmitted_by
        )

    async def mark_overdue(self, as_of: datetime.date | None = None) -> list[OnboardingInformationRequest]:
        """Spec 15.3's scheduled-process behaviour, exposed as a plain
        callable — see `application/scheduled_tasks.py` for how it's
        actually run periodically.
        """
        as_of = as_of or datetime.date.today()
        overdue = await self._requests.list_open_overdue(as_of)
        for request in overdue:
            request.status = "OVERDUE"
            await self._outbox.enqueue(
                OnboardingEvent.INFORMATION_REQUESTED,
                {
                    "applicationId": str(request.application_id),
                    "requestId": str(request.id),
                    "notificationCommand": OnboardingNotification.INFORMATION_REQUEST_OVERDUE,
                    "channel": "EMAIL",
                },
                aggregate_id=request.application_id,
            )
        return overdue
