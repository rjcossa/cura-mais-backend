"""Shared Pydantic base for camelCase-over-the-wire schemas.

Every module's API accepts and emits camelCase JSON (matching each
spec's request/response examples exactly) while Python code works with
normal snake_case attributes. Both Identity and Onboarding's `schemas.py`
subclass this rather than each defining their own — see
`app.modules.identity.application.schemas` and
`app.modules.onboarding.application.schemas`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
