"""Engine, session factory, FastAPI dependency and create_all helper."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base


def make_engine(url: str | None = None, **kwargs: object) -> Engine:
    """Create an engine (pool_pre_ping on). Defaults to DATABASE_URL; pass a URL for the test schema."""
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, **kwargs)  # type: ignore[arg-type]


_engine: Engine | None = None
SessionLocal: sessionmaker[Session] = sessionmaker(autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    """Lazily create the shared development engine and bind SessionLocal to it."""
    global _engine
    if _engine is None:
        _engine = make_engine()
        SessionLocal.configure(bind=_engine)
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    get_engine()
    with SessionLocal() as session:
        yield session


def create_all(engine: Engine | None = None) -> None:
    """Create every table that does not exist yet."""
    Base.metadata.create_all(engine or get_engine())


def create_views(engine: Engine) -> None:
    """Create or replace the SQL views (db/queries/views.sql). Tables must exist."""
    from app.services.kpi_sql import VIEWS_SQL_PATH, split_statements

    with engine.begin() as conn:
        for statement in split_statements(VIEWS_SQL_PATH.read_text(encoding="utf-8-sig")):
            conn.exec_driver_sql(statement.replace("%", "%%"))


def drop_all(engine: Engine) -> None:
    """Drop views and tables. Requires an explicit engine so it can never default to the development database."""
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP VIEW IF EXISTS v_readmission_base")
        conn.exec_driver_sql("DROP VIEW IF EXISTS v_active_encounters")
    Base.metadata.drop_all(engine)
