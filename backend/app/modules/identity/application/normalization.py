"""Identifier normalisation (spec sections 6.2 step 1-2, 12.3)."""

from __future__ import annotations

import phonenumbers
from phonenumbers import NumberParseException

from app.core.exceptions import ErrorField


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_mobile_number(raw: str, *, default_region: str = "MZ") -> str:
    """Normalises to E.164 (e.g. `+258841234567`). Raises `ValueError` with
    a user-facing message if the number cannot be parsed as valid.
    """
    try:
        parsed = phonenumbers.parse(raw, default_region)
    except NumberParseException as exc:
        raise ValueError("The mobile number format is invalid.") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("The mobile number format is invalid.")

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def try_normalize_mobile_number(raw: str, *, default_region: str = "MZ") -> tuple[str | None, ErrorField | None]:
    try:
        return normalize_mobile_number(raw, default_region=default_region), None
    except ValueError as exc:
        return None, ErrorField("mobileNumber", str(exc))
