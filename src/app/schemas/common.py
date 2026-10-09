"""Shared response shapes."""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ListMeta(BaseModel):
    """What the server applied, for debugging and for honest dashboards."""

    filters: dict[str, Any] = Field(default_factory=dict, description="the filters that were applied")
    sort_by: str | None = None
    sort_dir: str | None = None
    dates_simulated: bool | None = Field(None, description="true when rows contain the SIMULATED admission/discharge dates")


class Page(BaseModel, Generic[T]):
    """The one list envelope used by every list endpoint."""

    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
    meta: ListMeta
