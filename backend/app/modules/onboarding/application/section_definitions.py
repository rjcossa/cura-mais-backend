"""Section definitions per applicant type (spec section 5.3).

The spec gives example section *names* and one example section body
(PROFESSIONAL_REGISTRATION, spec 8.4) but doesn't fully specify every
section's required fields for every applicant type. `REQUIRED_FIELDS`
below is a reasonable, documented starting point — a back-office admin
with `ONBOARDING_RULE_MANAGE` would refine this over time in a real
deployment; nothing else in this module hard-codes assumptions beyond
"this section has these required keys," so tightening/loosening a
section's requirements never touches the workflow/completeness logic
itself.

The synthetic `DOCUMENTS` section's completion is *computed* from the
document-requirement resolution (are all mandatory documents AVAILABLE?)
rather than being freely editable via `PUT .../sections/DOCUMENTS` — spec
8.1's example response lists it as a section, but its content lives in
`onboarding_application_documents`, not arbitrary section JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SectionDefinition:
    code: str
    mandatory: bool = True
    required_fields: tuple[str, ...] = field(default_factory=tuple)


DOCUMENTS_SECTION_CODE = "DOCUMENTS"

_PERSONAL_INFORMATION = SectionDefinition(
    "PERSONAL_INFORMATION",
    required_fields=("fullName", "dateOfBirth", "nationalIdNumber", "address"),
)
_PROFESSIONAL_REGISTRATION = SectionDefinition(
    "PROFESSIONAL_REGISTRATION",
    required_fields=("registrationNumber", "registrationAuthority", "registrationCountry", "issueDate"),
)
_QUALIFICATIONS = SectionDefinition("QUALIFICATIONS", required_fields=("highestQualification", "institution"))
_DECLARATIONS = SectionDefinition(
    "DECLARATIONS",
    required_fields=("informationAccuracyConfirmed", "codeOfConductAccepted"),
)
_INSTITUTION_INFORMATION = SectionDefinition(
    "INSTITUTION_INFORMATION",
    required_fields=("legalName", "registrationNumber", "address"),
)
_OWNERSHIP = SectionDefinition("OWNERSHIP", required_fields=("owners",))
_BRANCH_INFORMATION = SectionDefinition("BRANCH_INFORMATION", required_fields=("branches",))
_BANKING_DETAILS = SectionDefinition(
    "BANKING_DETAILS", required_fields=("bankName", "accountNumber", "accountHolderName")
)
_REGULATORY_LICENCES = SectionDefinition("REGULATORY_LICENCES", required_fields=("licenceNumber", "issuingAuthority"))
_DOCUMENTS = SectionDefinition(DOCUMENTS_SECTION_CODE)  # completion computed, no editable fields

REQUIRED_SECTIONS: dict[str, tuple[SectionDefinition, ...]] = {
    "DOCTOR": (_PERSONAL_INFORMATION, _PROFESSIONAL_REGISTRATION, _QUALIFICATIONS, _DOCUMENTS, _DECLARATIONS),
    "NUTRITIONIST": (
        _PERSONAL_INFORMATION,
        _PROFESSIONAL_REGISTRATION,
        _QUALIFICATIONS,
        _DOCUMENTS,
        _DECLARATIONS,
    ),
    "HOSPITAL": (
        _INSTITUTION_INFORMATION,
        _OWNERSHIP,
        _BRANCH_INFORMATION,
        _BANKING_DETAILS,
        _DOCUMENTS,
        _DECLARATIONS,
    ),
    "CLINIC": (
        _INSTITUTION_INFORMATION,
        _OWNERSHIP,
        _BRANCH_INFORMATION,
        _BANKING_DETAILS,
        _DOCUMENTS,
        _DECLARATIONS,
    ),
    "PHARMACY": (
        _INSTITUTION_INFORMATION,
        _OWNERSHIP,
        _BRANCH_INFORMATION,
        _BANKING_DETAILS,
        _REGULATORY_LICENCES,
        _DOCUMENTS,
        _DECLARATIONS,
    ),
}


def get_section_definitions(applicant_type: str) -> tuple[SectionDefinition, ...]:
    return REQUIRED_SECTIONS.get(applicant_type, ())


def get_section_definition(applicant_type: str, section_code: str) -> SectionDefinition | None:
    for section in get_section_definitions(applicant_type):
        if section.code == section_code:
            return section
    return None


def compute_section_status(definition: SectionDefinition, data: dict) -> tuple[str, list[dict]]:
    """Returns (status, validation_errors). A boolean field (declarations)
    only counts as provided when explicitly `True`; every other field
    counts as provided when it has any truthy value.
    """
    if not data:
        return "NOT_STARTED", []

    missing = []
    for f in definition.required_fields:
        value = data.get(f)
        is_missing = value is not True if isinstance(value, bool) else not value
        if is_missing:
            missing.append({"field": f})

    if missing:
        return "IN_PROGRESS", missing
    return "COMPLETE", []
