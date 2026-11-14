from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator

from assistant.core.textutil import is_valid_email


def _check_email(value: str) -> str:
    value = value.strip()
    if not is_valid_email(value):
        raise ValueError(f"'{value}' is not a valid email address")
    return value


EmailAddress = Annotated[str, AfterValidator(_check_email)]
