"""Load the named KPI queries from db/queries/kpi_queries.sql and run them with bound parameters."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.config import PROJECT_ROOT

KPI_SQL_PATH = PROJECT_ROOT / "db" / "queries" / "kpi_queries.sql"
VIEWS_SQL_PATH = PROJECT_ROOT / "db" / "queries" / "views.sql"
_MARKER = re.compile(r"^--\s*name:\s*(\w+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class NamedQuery:
    """One query: its name, the business-question comment lines and the executable SQL (comments removed)."""

    name: str
    description: str
    sql: str


def split_statements(sql: str) -> list[str]:
    """Split a SQL script on statement-ending semicolons, dropping comment-only lines."""
    body = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    return [part.strip() for part in re.split(r";\s*(?:\n|$)", body) if part.strip()]


def load_named_queries(path: Path = KPI_SQL_PATH) -> dict[str, NamedQuery]:
    """Parse ``-- name: x`` blocks into NamedQuery objects."""
    content = path.read_text(encoding="utf-8-sig")
    marks = list(_MARKER.finditer(content))
    queries: dict[str, NamedQuery] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        block = content[mark.end():end]
        comments = [ln.lstrip("- ").strip() for ln in block.splitlines() if ln.strip().startswith("--")]
        body = "\n".join(ln for ln in block.splitlines() if not ln.strip().startswith("--")).strip().rstrip(";")
        queries[mark.group(1)] = NamedQuery(mark.group(1), " ".join(comments), body)
    return queries


def _native(value: Any) -> Any:
    """Decimal -> int when it is a whole number with no scale (a count), else float."""
    if isinstance(value, Decimal):
        return int(value) if value.as_tuple().exponent == 0 else float(value)
    return value


def run_query(conn: Connection, query: NamedQuery, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a named query and return rows as dicts of plain Python values."""
    result = conn.execute(text(query.sql), params or {})
    return [{k: _native(v) for k, v in row._mapping.items()} for row in result]
