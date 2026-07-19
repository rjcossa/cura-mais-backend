#!/usr/bin/env python
"""Idempotently seeds the initial roles and permissions (spec sections
4.3, 4.4) and a sensible default role -> permission mapping. Safe to
re-run — existing rows are left alone, only missing ones are inserted.

Usage:
    python -m scripts.seed_roles_permissions
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.database import get_session_factory  # noqa: E402
from app.modules.identity.domain.enums import PermissionCode, RoleCode  # noqa: E402
from app.modules.identity.domain.models import Permission, Role, RolePermission  # noqa: E402

ROLE_DEFINITIONS: dict[RoleCode, str] = {
    RoleCode.PATIENT: "Patient",
    RoleCode.DOCTOR_APPLICANT: "Doctor (pending approval)",
    RoleCode.DOCTOR: "Doctor",
    RoleCode.NUTRITIONIST_APPLICANT: "Nutritionist (pending approval)",
    RoleCode.NUTRITIONIST: "Nutritionist",
    RoleCode.HOSPITAL_ADMIN: "Hospital / clinic administrator",
    RoleCode.PHARMACY_ADMIN: "Pharmacy administrator",
    RoleCode.BACK_OFFICE_REVIEWER: "Back-office reviewer",
    RoleCode.BACK_OFFICE_APPROVER: "Back-office approver",
    RoleCode.SUPPORT_AGENT: "Support agent",
    RoleCode.PLATFORM_ADMIN: "Platform administrator",
}

PERMISSION_DESCRIPTIONS: dict[PermissionCode, str] = {
    PermissionCode.USER_SELF_READ: "Read own user record",
    PermissionCode.USER_SELF_UPDATE: "Update own user record",
    PermissionCode.SESSION_SELF_REVOKE: "Revoke own sessions",
    PermissionCode.ROLE_ASSIGN: "Assign a role to a user",
    PermissionCode.ROLE_REVOKE: "Revoke a role from a user",
    PermissionCode.USER_ADMIN_READ: "Read any user's account (admin)",
    PermissionCode.USER_ADMIN_SUSPEND: "Suspend a user account",
    PermissionCode.USER_ADMIN_ACTIVATE: "Reactivate a user account",
    PermissionCode.SESSION_ADMIN_REVOKE: "Revoke any user's sessions (admin)",
    # Onboarding: applicant self-service
    PermissionCode.ONBOARDING_APPLICATION_READ_SELF: "Read own onboarding application",
    PermissionCode.ONBOARDING_APPLICATION_UPDATE_SELF: "Update own onboarding application",
    PermissionCode.ONBOARDING_APPLICATION_SUBMIT_SELF: "Submit own onboarding application",
    PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF: "Upload/replace/delete own onboarding documents",
    PermissionCode.ONBOARDING_INFORMATION_REQUEST_READ_SELF: "Read information requests on own application",
    PermissionCode.ONBOARDING_INFORMATION_REQUEST_RESPOND_SELF: "Respond to information requests on own application",
    PermissionCode.ONBOARDING_APPLICATION_WITHDRAW_SELF: "Withdraw own onboarding application",
    # Onboarding: reviewer
    PermissionCode.ONBOARDING_APPLICATION_SEARCH: "Search onboarding applications",
    PermissionCode.ONBOARDING_APPLICATION_READ: "Read any onboarding application",
    PermissionCode.ONBOARDING_APPLICATION_ASSIGN: "Assign an onboarding application to a reviewer",
    PermissionCode.ONBOARDING_APPLICATION_CLAIM: "Claim an unassigned onboarding application",
    PermissionCode.ONBOARDING_REVIEW_START: "Start a review on an onboarding application",
    PermissionCode.ONBOARDING_CHECKLIST_UPDATE: "Update review checklist items",
    PermissionCode.ONBOARDING_DOCUMENT_REVIEW: "Accept/reject an onboarding application document",
    PermissionCode.ONBOARDING_VERIFICATION_EXECUTE: "Create/complete verification checks",
    PermissionCode.ONBOARDING_INFORMATION_REQUEST: "Create information requests on an application",
    PermissionCode.ONBOARDING_REVIEW_COMPLETE: "Complete a review with a recommendation",
    PermissionCode.ONBOARDING_RISK_FLAG_MANAGE: "Raise/resolve onboarding risk flags",
    # Onboarding: approver (deliberately NOT granted to BACK_OFFICE_REVIEWER — maker-checker)
    PermissionCode.ONBOARDING_APPLICATION_APPROVE: "Approve an onboarding application",
    PermissionCode.ONBOARDING_APPLICATION_CONDITIONALLY_APPROVE: "Conditionally approve an onboarding application",
    PermissionCode.ONBOARDING_APPLICATION_REJECT: "Reject an onboarding application",
    PermissionCode.ONBOARDING_APPLICANT_SUSPEND: "Suspend an approved applicant/provider",
    PermissionCode.ONBOARDING_APPLICANT_REINSTATE: "Reinstate a suspended applicant/provider",
    # Onboarding: administrative
    PermissionCode.ONBOARDING_RULE_MANAGE: "Manage onboarding document requirement rules",
    PermissionCode.ONBOARDING_CHECKLIST_MANAGE: "Manage onboarding review checklist templates",
    PermissionCode.ONBOARDING_APPLICATION_REASSIGN: "Reassign an onboarding application between reviewers",
    PermissionCode.ONBOARDING_DECISION_CORRECT: "Issue an administrative correction to a final decision",
    PermissionCode.ONBOARDING_AUDIT_READ: "Read onboarding audit/history records",
    # Providers: self-service
    PermissionCode.PROVIDER_PROFILE_READ_SELF: "Read own provider profile",
    PermissionCode.PROVIDER_PROFILE_UPDATE_SELF: "Update own provider profile",
    PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF: "Manage own professional registrations",
    PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF: "Manage own qualifications",
    PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF: "Manage own specialities",
    PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF: "Manage own consultation languages",
    PermissionCode.PROVIDER_SERVICE_MANAGE_SELF: "Manage own services",
    PermissionCode.PROVIDER_LOCATION_MANAGE_SELF: "Manage own practice locations",
    PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF: "Manage own institution affiliations",
    PermissionCode.PROVIDER_PUBLICATION_MANAGE_SELF: "Publish/unpublish own provider profile",
    # Providers: back office
    PermissionCode.PROVIDER_SEARCH: "Search provider profiles",
    PermissionCode.PROVIDER_READ: "Read any provider profile",
    PermissionCode.PROVIDER_CORRECT: "Administratively correct provider data",
    PermissionCode.PROVIDER_HIDE: "Administratively hide a provider profile",
    PermissionCode.PROVIDER_SUSPEND: "Suspend a provider profile",
    PermissionCode.PROVIDER_REINSTATE: "Reinstate a provider",
    PermissionCode.PROVIDER_STATUS_HISTORY_READ: "Read provider status history",
    PermissionCode.PROVIDER_PUBLICATION_HISTORY_READ: "Read provider publication history",
    PermissionCode.PROVIDER_AFFILIATION_CONFIRM: "Confirm a provider's institution affiliation",
    PermissionCode.PROVIDER_AFFILIATION_REJECT: "Reject a provider's institution affiliation",
}

# Every authenticated user gets these regardless of role — anyone might
# start an onboarding application (a patient becoming a doctor, an
# existing doctor adding a nutrition credential, etc.), so these are not
# gated by a specific applicant-type role the way approval/review
# permissions are.
BASE_PERMISSIONS = {
    PermissionCode.USER_SELF_READ,
    PermissionCode.USER_SELF_UPDATE,
    PermissionCode.SESSION_SELF_REVOKE,
    PermissionCode.ONBOARDING_APPLICATION_READ_SELF,
    PermissionCode.ONBOARDING_APPLICATION_UPDATE_SELF,
    PermissionCode.ONBOARDING_APPLICATION_SUBMIT_SELF,
    PermissionCode.ONBOARDING_DOCUMENT_MANAGE_SELF,
    PermissionCode.ONBOARDING_INFORMATION_REQUEST_READ_SELF,
    PermissionCode.ONBOARDING_INFORMATION_REQUEST_RESPOND_SELF,
    PermissionCode.ONBOARDING_APPLICATION_WITHDRAW_SELF,
}

# Reviewer-level onboarding permissions (spec 25.2) — granted to reviewers
# AND approvers (an approver can also review), but deliberately NOT
# bundled with approval permissions below.
ONBOARDING_REVIEWER_PERMISSIONS = {
    PermissionCode.ONBOARDING_APPLICATION_SEARCH,
    PermissionCode.ONBOARDING_APPLICATION_READ,
    PermissionCode.ONBOARDING_APPLICATION_ASSIGN,
    PermissionCode.ONBOARDING_APPLICATION_CLAIM,
    PermissionCode.ONBOARDING_REVIEW_START,
    PermissionCode.ONBOARDING_CHECKLIST_UPDATE,
    PermissionCode.ONBOARDING_DOCUMENT_REVIEW,
    PermissionCode.ONBOARDING_VERIFICATION_EXECUTE,
    PermissionCode.ONBOARDING_INFORMATION_REQUEST,
    PermissionCode.ONBOARDING_REVIEW_COMPLETE,
    PermissionCode.ONBOARDING_RISK_FLAG_MANAGE,
}

# Approval-level onboarding permissions (spec 25.3). Per spec 16.1's
# maker-checker rule, the final approver must not be the initial
# reviewer — reflected here by BACK_OFFICE_REVIEWER never receiving
# these, only BACK_OFFICE_APPROVER and PLATFORM_ADMIN. The application
# layer also re-checks this at decision time (spec: "must verify the
# maker-checker rule at decision time, not only in the user interface"),
# since permission alone can't tell two BACK_OFFICE_APPROVER users apart.
ONBOARDING_APPROVER_PERMISSIONS = {
    PermissionCode.ONBOARDING_APPLICATION_APPROVE,
    PermissionCode.ONBOARDING_APPLICATION_CONDITIONALLY_APPROVE,
    PermissionCode.ONBOARDING_APPLICATION_REJECT,
    PermissionCode.ONBOARDING_APPLICANT_SUSPEND,
    PermissionCode.ONBOARDING_APPLICANT_REINSTATE,
}

# Providers: self-service (spec 32.1) — granted only to the roles that can
# actually hold a provider profile, unlike BASE_PERMISSIONS' onboarding
# self-service grants (which any authenticated user gets, since anyone
# might start an onboarding application).
PROVIDER_SELF_PERMISSIONS = {
    PermissionCode.PROVIDER_PROFILE_READ_SELF,
    PermissionCode.PROVIDER_PROFILE_UPDATE_SELF,
    PermissionCode.PROVIDER_REGISTRATION_MANAGE_SELF,
    PermissionCode.PROVIDER_QUALIFICATION_MANAGE_SELF,
    PermissionCode.PROVIDER_SPECIALITY_MANAGE_SELF,
    PermissionCode.PROVIDER_LANGUAGE_MANAGE_SELF,
    PermissionCode.PROVIDER_SERVICE_MANAGE_SELF,
    PermissionCode.PROVIDER_LOCATION_MANAGE_SELF,
    PermissionCode.PROVIDER_AFFILIATION_MANAGE_SELF,
    PermissionCode.PROVIDER_PUBLICATION_MANAGE_SELF,
}

# Providers: back office (spec 32.3) plus the institution-confirmation
# stand-in (spec 32.4, 17.7). Unlike Onboarding's reviewer/approver split,
# the Providers spec doesn't define its own maker-checker distinction for
# these, so both back-office roles get the full set; PLATFORM_ADMIN
# already gets everything via `set(PermissionCode)` below.
PROVIDER_BACKOFFICE_PERMISSIONS = {
    PermissionCode.PROVIDER_SEARCH,
    PermissionCode.PROVIDER_READ,
    PermissionCode.PROVIDER_CORRECT,
    PermissionCode.PROVIDER_HIDE,
    PermissionCode.PROVIDER_SUSPEND,
    PermissionCode.PROVIDER_REINSTATE,
    PermissionCode.PROVIDER_STATUS_HISTORY_READ,
    PermissionCode.PROVIDER_PUBLICATION_HISTORY_READ,
    PermissionCode.PROVIDER_AFFILIATION_CONFIRM,
    PermissionCode.PROVIDER_AFFILIATION_REJECT,
}

ROLE_PERMISSIONS: dict[RoleCode, set[PermissionCode]] = {
    RoleCode.PATIENT: BASE_PERMISSIONS,
    RoleCode.DOCTOR_APPLICANT: BASE_PERMISSIONS | PROVIDER_SELF_PERMISSIONS,
    RoleCode.DOCTOR: BASE_PERMISSIONS | PROVIDER_SELF_PERMISSIONS,
    RoleCode.NUTRITIONIST_APPLICANT: BASE_PERMISSIONS | PROVIDER_SELF_PERMISSIONS,
    RoleCode.NUTRITIONIST: BASE_PERMISSIONS | PROVIDER_SELF_PERMISSIONS,
    RoleCode.HOSPITAL_ADMIN: BASE_PERMISSIONS,
    RoleCode.PHARMACY_ADMIN: BASE_PERMISSIONS,
    RoleCode.SUPPORT_AGENT: BASE_PERMISSIONS | {PermissionCode.USER_ADMIN_READ},
    RoleCode.BACK_OFFICE_REVIEWER: BASE_PERMISSIONS
    | {PermissionCode.USER_ADMIN_READ}
    | ONBOARDING_REVIEWER_PERMISSIONS
    | PROVIDER_BACKOFFICE_PERMISSIONS,
    RoleCode.BACK_OFFICE_APPROVER: BASE_PERMISSIONS
    | {
        PermissionCode.USER_ADMIN_READ,
        PermissionCode.USER_ADMIN_SUSPEND,
        PermissionCode.USER_ADMIN_ACTIVATE,
        PermissionCode.ROLE_ASSIGN,
        PermissionCode.ROLE_REVOKE,
        PermissionCode.SESSION_ADMIN_REVOKE,
        PermissionCode.ONBOARDING_AUDIT_READ,
    }
    | ONBOARDING_REVIEWER_PERMISSIONS
    | ONBOARDING_APPROVER_PERMISSIONS
    | PROVIDER_BACKOFFICE_PERMISSIONS,
    RoleCode.PLATFORM_ADMIN: BASE_PERMISSIONS | set(PermissionCode),
}


async def seed() -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing_roles = {
            r.code: r for r in (await session.execute(select(Role))).scalars().all()
        }
        existing_permissions = {
            p.code: p for p in (await session.execute(select(Permission))).scalars().all()
        }

        for role_code, name in ROLE_DEFINITIONS.items():
            if role_code.value not in existing_roles:
                role = Role(code=role_code.value, name=name)
                session.add(role)
                existing_roles[role_code.value] = role
                print(f"+ role {role_code.value}")

        for perm_code, description in PERMISSION_DESCRIPTIONS.items():
            if perm_code.value not in existing_permissions:
                perm = Permission(code=perm_code.value, description=description)
                session.add(perm)
                existing_permissions[perm_code.value] = perm
                print(f"+ permission {perm_code.value}")

        await session.flush()  # populate IDs for newly-inserted rows

        existing_pairs = {
            (rp.role_id, rp.permission_id)
            for rp in (await session.execute(select(RolePermission))).scalars().all()
        }

        for role_code, perm_codes in ROLE_PERMISSIONS.items():
            role = existing_roles[role_code.value]
            for perm_code in perm_codes:
                perm = existing_permissions[perm_code.value]
                if (role.id, perm.id) not in existing_pairs:
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))
                    print(f"+ {role_code.value} -> {perm_code.value}")

        await session.commit()
        print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
