"""Operational list endpoints (audit logs, pipeline runs, DQ issues) and user management, on the shared query helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AppUser, AuditLog, DqIssue, PipelineRun
from app.schemas.admin import UserCreate
from app.security import hash_password
from app.services import audit
from app.services.audit import AuditContext
from app.services.query_helpers import (
    PageParams, SortSpec, apply_filters, apply_sort, check_date_range, inclusive_day_range, paginate,
)

AUDIT_SORT = SortSpec({"created_at": AuditLog.created_at, "id": AuditLog.id}, "created_at", AuditLog.id)
RUN_SORT = SortSpec({"started_at": PipelineRun.started_at, "run_id": PipelineRun.run_id}, "started_at", PipelineRun.run_id)
DQ_SORT = SortSpec({"issue_id": DqIssue.issue_id, "rule_name": DqIssue.rule_name}, "issue_id", DqIssue.issue_id)
USER_SORT = SortSpec({"user_id": AppUser.user_id, "username": AppUser.username}, "user_id", AppUser.user_id)


def _rows(session: Session, stmt: Any, params: PageParams, model: Any) -> dict[str, Any]:
    return paginate(session, stmt, params, lambda r: {c.name: getattr(r[0], c.name) for c in model.__table__.columns})


def list_audit_logs(session: Session, params: PageParams, f: dict[str, Any], sort_by: str, sort_dir: str) -> dict[str, Any]:
    """Filters: user (username), action, entity_type, entity_id, date_from/date_to (whole days, inclusive)."""
    check_date_range(f.get("date_from"), f.get("date_to"))
    stmt = apply_filters(select(AuditLog), [
        AuditLog.username == f["user"] if f.get("user") else None,
        AuditLog.action == f["action"] if f.get("action") else None,
        AuditLog.entity_type == f["entity_type"] if f.get("entity_type") else None,
        AuditLog.entity_id == f["entity_id"] if f.get("entity_id") else None,
        *inclusive_day_range(AuditLog.created_at, f.get("date_from"), f.get("date_to"), is_datetime=True)])
    return _rows(session, apply_sort(stmt, AUDIT_SORT, sort_by, sort_dir), params, AuditLog)


def list_pipeline_runs(session: Session, params: PageParams, f: dict[str, Any], sort_by: str, sort_dir: str) -> dict[str, Any]:
    """Filters: status, date_from/date_to on started_at."""
    check_date_range(f.get("date_from"), f.get("date_to"))
    stmt = apply_filters(select(PipelineRun), [
        PipelineRun.status == f["status"] if f.get("status") else None,
        *inclusive_day_range(PipelineRun.started_at, f.get("date_from"), f.get("date_to"), is_datetime=True)])
    return _rows(session, apply_sort(stmt, RUN_SORT, sort_by, sort_dir), params, PipelineRun)


def list_dq_issues(session: Session, params: PageParams, f: dict[str, Any], sort_by: str, sort_dir: str) -> dict[str, Any]:
    """Filters: run_id, rule_name, severity."""
    stmt = apply_filters(select(DqIssue), [
        DqIssue.run_id == f["run_id"] if f.get("run_id") is not None else None,
        DqIssue.rule_name == f["rule_name"] if f.get("rule_name") else None,
        DqIssue.severity == f["severity"] if f.get("severity") else None])
    return _rows(session, apply_sort(stmt, DQ_SORT, sort_by, sort_dir), params, DqIssue)


def _user_dict(user: AppUser) -> dict[str, Any]:
    """Public view of a user: never the password hash."""
    return {"user_id": user.user_id, "username": user.username, "role": user.role, "is_active": bool(user.is_active),
            "last_login_at": user.last_login_at, "created_at": user.created_at}


def list_users(session: Session, params: PageParams, sort_by: str, sort_dir: str) -> dict[str, Any]:
    stmt = apply_sort(select(AppUser), USER_SORT, sort_by, sort_dir)
    return paginate(session, stmt, params, lambda r: _user_dict(r[0]))


def create_user(session: Session, ctx: AuditContext, data: UserCreate) -> dict[str, Any]:
    """Hash the password, insert the user (409 if the username is taken) and audit CREATE without any secret."""
    if session.scalar(select(AppUser.user_id).where(AppUser.username == data.username)) is not None:
        raise ApiError(409, "conflict", f"Username '{data.username}' already exists")
    user = AppUser(username=data.username, password_hash=hash_password(data.password), role=data.role)
    session.add(user)
    try:
        session.flush()
        audit.record(session, ctx, "CREATE", "user", user.user_id, None,
                     {"username": user.username, "role": user.role, "is_active": True})
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(409, "conflict", f"Username '{data.username}' already exists") from None
    session.refresh(user)
    return _user_dict(user)


