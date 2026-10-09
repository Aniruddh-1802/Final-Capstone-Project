"""db/indexes.sql, the ORM models and the generated DDL must describe the same indexes (L12)."""
from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Engine, text

from app.models import Base
from apply_indexes import INDEX_SQL, parse_indexes, apply_indexes
from export_ddl import build_ddl


def model_indexes() -> set[tuple[str, str, tuple[str, ...]]]:
    return {(i.name, t.name, tuple(c.name for c in i.columns)) for t in Base.metadata.sorted_tables for i in t.indexes}


def file_indexes() -> set[tuple[str, str, tuple[str, ...]]]:
    return {(name, table, tuple(cols)) for name, table, cols in parse_indexes(INDEX_SQL.read_text(encoding="utf-8-sig"))}


def test_indexes_sql_matches_the_model_definitions() -> None:
    assert file_indexes() == model_indexes() and len(file_indexes()) == 4


def test_schema_sql_contains_every_index() -> None:
    ddl = build_ddl()
    for name, table, cols in file_indexes():
        assert re.search(rf"CREATE INDEX {name} ON {table} \({', '.join(cols)}\)", ddl), name


def test_built_database_has_the_indexes_and_apply_is_idempotent(engine: Engine) -> None:
    with engine.connect() as conn:
        found = {r[0] for r in conn.execute(text("SELECT DISTINCT index_name FROM information_schema.statistics "
                                                  "WHERE table_schema = DATABASE() AND index_name LIKE 'ix\\_%'"))}
    assert found == {name for name, _, _ in file_indexes()}
    assert apply_indexes(engine) == []  # nothing missing, nothing created twice


def test_view_still_hides_soft_deleted_patients_with_the_anti_join(engine: Engine) -> None:
    raw = (Path(__file__).resolve().parents[1] / "db" / "queries" / "views.sql").read_text(encoding="utf-8-sig")
    sql = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("--"))  # ignore explanatory comments
    assert "NOT EXISTS" in sql and "JOIN patients" not in sql  # the performance rewrite is in place
