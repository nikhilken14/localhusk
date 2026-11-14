from __future__ import annotations

from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel, model_validator

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envelope used by every endpoint that supports pagination."""

    items: list[T]
    total: int
    limit: int
    offset: int


class PatchModel(BaseModel):
    """Base for PATCH bodies: unset fields are ignored, but explicit ``null`` is rejected for
    columns that cannot be null (otherwise the request would crash with a DB error)."""

    non_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_for_required(self):
        for name in self.model_fields_set:
            if name in self.non_nullable and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self
