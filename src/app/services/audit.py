"""Audit trail: one audit_logs row per CREATE / UPDATE / DELETE / EXPORT, written in the caller's transaction.

``record`` only adds the row to the session; the caller commits once, so the data change and its audit row commit
or roll back together. Never pass passwords, hashes or tokens as before/after: ``scrub`` removes known secret keys
as a safety net.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.deps import CurrentUser
from app.models import AuditLog
from utils.request_context import request_id_var

log = logging.getLogger(__name__)
SECRET_KEYS = frozenset({"password", "password_hash", "token", "access_token", "authorization", "secret", "jwt_secret"})


@dataclass(frozen=True)
class AuditContext:
    """Who is acting and from where; built once per request."""

    user: CurrentUser
    request_id: str
    ip_address: str | None


def audit_context(request: Request, user: CurrentUser) -> AuditContext:
    """Create the context from the request (client IP as seen by the server) and the authenticated user."""
    ip = request.client.host if request.client else None
    return AuditContext(user=user, request_id=request_id_var.get(), ip_address=ip)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items() if str(k).lower() not in SECRET_KEYS}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def scrub(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """JSON-safe copy of ``data`` without secret keys (dates become ISO strings)."""
    return None if data is None else _jsonable(data)


def record(session: Session, ctx: AuditContext, action: str, entity_type: str, entity_id: object,
           before: dict[str, Any] | None, after: dict[str, Any] | None) -> AuditLog:
    """Add one audit row (flushed, not committed). ``action`` is CREATE, UPDATE, DELETE or EXPORT."""
    row = AuditLog(user_id=ctx.user.user_id, username=ctx.user.username, role=ctx.user.role, action=action,
                   entity_type=entity_type, entity_id=str(entity_id), before_json=scrub(before),
                   after_json=scrub(after), request_id=ctx.request_id, ip_address=ctx.ip_address)
    session.add(row)
    session.flush()
    log.info("audit %s %s %s by user_id=%s", action, entity_type, entity_id, ctx.user.user_id)
    return row
