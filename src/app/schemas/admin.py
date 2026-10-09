"""Admin / operations schemas. Nothing here ever carries a password hash or a token."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditLogOut(BaseModel):
    id: int
    created_at: datetime
    user_id: int | None
    username: str
    role: str
    action: str
    entity_type: str
    entity_id: str
    before_json: Any | None
    after_json: Any | None
    request_id: str | None
    ip_address: str | None


class PipelineRunOut(BaseModel):
    run_id: int
    source_file: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_read: int
    rows_loaded: int
    rows_rejected: int
    rows_skipped_existing: int
    dq_summary_json: Any | None
    error_message: str | None
    triggered_by: str


class DqIssueOut(BaseModel):
    issue_id: int
    run_id: int
    encounter_id: int | None
    rule_name: str
    severity: str
    column_name: str | None
    bad_value: str | None
    action: str


class AdminUserOut(BaseModel):
    user_id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    """Create a login. The password is hashed with bcrypt and never returned or logged."""

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"username": "new.analyst", "password": "a-long-passphrase-123", "role": "analyst"}]})

    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,50}$")
    password: str = Field(min_length=12, max_length=72)
    role: Literal["administrator", "clinical_ops", "analyst"]

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value
