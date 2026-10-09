"""Application settings loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed configuration. Real values live in .env (git-ignored)."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str
    test_database_url: str = ""
    jwt_secret: str = ""
    jwt_expire_minutes: int = 60
    incoming_dir: str = "data/incoming"
    rejected_dir: str = "data/rejected"
    reports_dir: str = "data/reports"
    log_dir: str = "logs"
    max_reject_ratio: float = 0.2
    chunk_size: int = 5000

    def resolve_path(self, value: str) -> Path:
        """Resolve a configured folder against the repository root unless it is already absolute."""
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings instance."""
    return Settings()  # type: ignore[call-arg]
