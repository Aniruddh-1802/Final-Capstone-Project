"""Shared fixtures. Database tests run ONLY against TEST_DATABASE_URL (healthcare_test), never healthcare_db."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from app.config import get_settings
from app.database import create_all, create_views, drop_all, make_engine


def _test_url() -> str:
    url = get_settings().test_database_url
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    name = make_url(url).database or ""
    if name == make_url(get_settings().database_url).database or not name.endswith("_test"):
        pytest.fail(f"Refusing to run tests against database {name!r}: it must be a *_test schema")
    return url


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine bound to the test schema; tables are rebuilt once per session."""
    eng = make_engine(_test_url())
    drop_all(eng)
    create_all(eng)
    create_views(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def clean_db(engine: Engine) -> Engine:
    """Empty every table before a test (test schema only)."""
    from app.models import Base

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"TRUNCATE TABLE `{table.name}`"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    return engine
