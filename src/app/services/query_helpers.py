"""Reusable list-query helpers: AND-combined filters, whitelisted sorting with a primary-key tiebreaker, pagination.

No user-supplied text ever reaches a SQL string: sort names are looked up in a whitelist of column objects, filter
values are bound parameters, and LIKE patterns are escaped by SQLAlchemy (``startswith(..., autoescape=True)``).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import Query
from sqlalchemy import ColumnElement, Select, and_, func, select
from sqlalchemy.orm import Session

from app.errors import ApiError

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


@dataclass(frozen=True)
class PageParams:
    """Validated ``page`` / ``page_size`` query parameters (FastAPI answers 422 for out-of-range values)."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


def page_params(page: int = Query(1, ge=1, description="1-based page number"),
                page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE,
                                       description=f"rows per page, 1..{MAX_PAGE_SIZE}")) -> PageParams:
    """FastAPI dependency."""
    return PageParams(page, page_size)


@dataclass(frozen=True)
class SortSpec:
    """Public sort names -> column objects, a default, and the unique column used as the final tiebreaker."""

    columns: dict[str, ColumnElement[Any]]
    default: str
    tiebreaker: ColumnElement[Any]

    def names(self) -> tuple[str, ...]:
        return tuple(self.columns)


def validation_error(field: str, message: str, where: str = "query") -> ApiError:
    """422 in the uniform contract with a field-level detail."""
    return ApiError(422, "validation_error", "Request validation failed",
                    [{"loc": [where, field], "msg": message, "type": "value_error"}])


def check_date_range(date_from: date | None, date_to: date | None) -> None:
    """422 unless date_from <= date_to (either may be missing)."""
    if date_from and date_to and date_from > date_to:
        raise validation_error("date_from", "date_from must not be after date_to")


def apply_filters(stmt: Select[Any], conditions: Sequence[ColumnElement[bool] | None]) -> Select[Any]:
    """AND together the conditions that are not None (a None condition means the filter was not supplied)."""
    active = [c for c in conditions if c is not None]
    return stmt.where(and_(*active)) if active else stmt


def inclusive_day_range(column: ColumnElement[Any], date_from: date | None, date_to: date | None,
                        is_datetime: bool = False) -> list[ColumnElement[bool]]:
    """Both ends inclusive. For DATETIME columns date_to means 'up to the end of that day' (< next midnight)."""
    out: list[ColumnElement[bool]] = []
    if date_from:
        out.append(column >= (datetime.combine(date_from, datetime.min.time()) if is_datetime else date_from))
    if date_to:
        out.append(column < datetime.combine(date_to + timedelta(days=1), datetime.min.time())
                   if is_datetime else column <= date_to)
    return out


def apply_sort(stmt: Select[Any], spec: SortSpec, sort_by: str | None, sort_dir: str = "desc") -> Select[Any]:
    """ORDER BY the whitelisted column, then the primary key (same direction) so paging is deterministic."""
    name = sort_by or spec.default
    if name not in spec.columns:
        raise validation_error("sort_by", f"sort_by must be one of: {', '.join(spec.names())}")
    if sort_dir not in ("asc", "desc"):
        raise validation_error("sort_dir", "sort_dir must be asc or desc")
    primary = spec.columns[name]
    order = (primary.asc(), spec.tiebreaker.asc()) if sort_dir == "asc" else (primary.desc(), spec.tiebreaker.desc())
    return stmt.order_by(*order)


def paginate(session: Session, stmt: Select[Any], params: PageParams,
             map_row: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Run the count and the page query; return ``{items, total, page, page_size, pages}``.

    A page beyond the last returns an empty ``items`` list with the correct ``total``.
    """
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = session.execute(stmt.limit(params.page_size).offset((params.page - 1) * params.page_size)).all()
    items = [map_row(r) if map_row else r for r in rows]
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size,
            "pages": math.ceil(total / params.page_size) if total else 0}


def envelope(page: dict[str, Any], filters: dict[str, Any], sort_by: str, sort_dir: str,
             dates_simulated: bool = False) -> dict[str, Any]:
    """Add ``meta`` (applied filters and sort) to a paginate() result; same shape for every list endpoint."""
    applied = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in filters.items()
               if v is not None}
    meta: dict[str, Any] = {"filters": applied, "sort_by": sort_by, "sort_dir": sort_dir}
    if dates_simulated:
        meta["dates_simulated"] = True
    return {**page, "meta": meta}
