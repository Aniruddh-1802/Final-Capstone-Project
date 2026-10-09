"""Admin endpoints: audit logs, pipeline runs, DQ issues and user management (all on the shared list helpers)."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.deps import CurrentUser, DbSession, require_capability
from app.schemas.admin import AdminUserOut, AuditLogOut, DqIssueOut, PipelineRunOut, UserCreate
from app.schemas.common import Page
from app.services import admin as service
from app.services.audit import audit_context
from app.services.query_helpers import PageParams, envelope, page_params

router = APIRouter(prefix="/admin", tags=["admin"])
Auditor = Annotated[CurrentUser, Depends(require_capability("view_audit"))]
Operator = Annotated[CurrentUser, Depends(require_capability("view_pipeline"))]
UserAdmin = Annotated[CurrentUser, Depends(require_capability("manage_users"))]
Paging = Annotated[PageParams, Depends(page_params)]
Direction = Literal["asc", "desc"]


@router.get("/audit-logs", response_model=Page[AuditLogOut], summary="Audit trail (administrator)")
def audit_logs(db: DbSession, user: Auditor, params: Paging,
               user_name: str | None = Query(None, alias="user", max_length=50, description="username"),
               action: Literal["CREATE", "UPDATE", "DELETE", "EXPORT"] | None = None,
               entity_type: str | None = Query(None, max_length=30), entity_id: str | None = Query(None, max_length=40),
               date_from: date | None = None, date_to: date | None = Query(None, description="whole day, inclusive"),
               sort_by: Literal["created_at", "id"] = "created_at", sort_dir: Direction = "desc") -> dict:
    """Newest first by default; ties broken by id."""
    f = {"user": user_name, "action": action, "entity_type": entity_type, "entity_id": entity_id,
         "date_from": date_from, "date_to": date_to}
    return envelope(service.list_audit_logs(db, params, f, sort_by, sort_dir), f, sort_by, sort_dir)


@router.get("/pipeline-runs", response_model=Page[PipelineRunOut], summary="ETL run history")
def pipeline_runs(db: DbSession, user: Operator, params: Paging,
                  status: Literal["RUNNING", "SUCCESS", "FAILED", "SKIPPED_DUPLICATE_FILE"] | None = None,
                  date_from: date | None = None, date_to: date | None = Query(None, description="whole day, inclusive"),
                  sort_by: Literal["started_at", "run_id"] = "started_at", sort_dir: Direction = "desc") -> dict:
    f = {"status": status, "date_from": date_from, "date_to": date_to}
    return envelope(service.list_pipeline_runs(db, params, f, sort_by, sort_dir), f, sort_by, sort_dir)


@router.get("/dq-issues", response_model=Page[DqIssueOut], summary="Row-level data-quality findings")
def dq_issues(db: DbSession, user: Operator, params: Paging, run_id: int | None = Query(None, ge=1),
              rule_name: str | None = Query(None, max_length=20),
              severity: Literal["error", "warning", "info"] | None = None,
              sort_by: Literal["issue_id", "rule_name"] = "issue_id", sort_dir: Direction = "asc") -> dict:
    f = {"run_id": run_id, "rule_name": rule_name, "severity": severity}
    return envelope(service.list_dq_issues(db, params, f, sort_by, sort_dir), f, sort_by, sort_dir)


@router.get("/users", response_model=Page[AdminUserOut], summary="List users (never includes password hashes)")
def users(db: DbSession, user: UserAdmin, params: Paging,
          sort_by: Literal["user_id", "username"] = "user_id", sort_dir: Direction = "asc") -> dict:
    return envelope(service.list_users(db, params, sort_by, sort_dir), {}, sort_by, sort_dir)


@router.post("/users", response_model=AdminUserOut, status_code=201, summary="Create a user (administrator)")
def create_user(body: UserCreate, request: Request, db: DbSession, user: UserAdmin) -> dict:
    """409 if the username exists. Audited (CREATE) without any secret."""
    return service.create_user(db, audit_context(request, user), body)
