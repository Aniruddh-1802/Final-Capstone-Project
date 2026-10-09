"""Report downloads (CSV / Excel) and the export history. Aggregated reports: all roles. Encounter-level: administrator and
clinical_ops only, capped at 50,000 rows, audited as EXPORT."""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.deps import CurrentUser, DbSession, get_current_user, require_capability
from app.errors import ApiError
from app.models import ReportRun
from app.permissions import roles_for
from app.routers.analytics import shared_filters
from app.schemas.common import Page
from app.services import audit
from app.services.audit import audit_context
from app.services.query_helpers import PageParams, SortSpec, apply_filters, apply_sort, check_date_range, envelope, inclusive_day_range, page_params, paginate
from etl import reports

router = APIRouter(prefix="/reports", tags=["reports"])
Filters = Annotated[dict[str, Any], Depends(shared_filters)]
Operator = Annotated[CurrentUser, Depends(require_capability("view_pipeline"))]
CHUNK = 64 * 1024
HISTORY_SORT = SortSpec({"generated_at": ReportRun.generated_at, "report_id": ReportRun.report_id}, "generated_at", ReportRun.report_id)


class ReportRunOut(BaseModel):
    report_id: int
    report_type: str
    file_path: str
    row_count: int
    filters_json: Any | None
    generated_at: datetime
    triggered_by: str


def _stream(content: bytes):
    buf = io.BytesIO(content)
    while chunk := buf.read(CHUNK):
        yield chunk


@router.get("/export", summary="Download a report as CSV or Excel",
            responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}},
                       403: {"description": "role may not export this report"},
                       413: {"description": "encounter-level export over the 50,000 row cap"}})
def export_report(request: Request, db: DbSession, user: Annotated[CurrentUser, Depends(get_current_user)], f: Filters,
                  report: Literal["admissions_trend", "readmission_summary", "length_of_stay_summary", "encounters"],
                  format: Literal["csv", "xlsx"] = "xlsx") -> StreamingResponse:
    """Uses the shared analytics filters. The encounters report needs the export_encounters capability."""
    capability = "export_encounters" if report == "encounters" else "export_aggregated"
    if user.role not in roles_for(capability):
        raise ApiError(403, "forbidden", "You do not have permission to export this report")
    try:
        result = reports.build_report(db, report, f, format, triggered_by=user.username)
    except reports.ReportTooLarge as exc:
        raise ApiError(413, "export_too_large", str(exc), {"rows": exc.rows, "limit": exc.cap}) from None
    reports.record_run(db, result, user.username)
    if report == "encounters":
        audit.record(db, audit_context(request, user), "EXPORT", "report", result.filename, None,
                     {"report": report, "format": format, "filters": result.filters, "rows": result.row_count})
    db.commit()  # report_runs row and audit row commit together
    headers = {"Content-Disposition": f'attachment; filename="{result.filename}"', "X-Row-Count": str(result.row_count),
               "Access-Control-Expose-Headers": "Content-Disposition, X-Row-Count"}
    return StreamingResponse(_stream(result.content), media_type=result.content_type, headers=headers)


@router.get("/history", response_model=Page[ReportRunOut], summary="Generated reports (administrator, clinical_ops)")
def history(db: DbSession, user: Operator, params: Annotated[PageParams, Depends(page_params)],
            report_type: Literal["admissions_trend", "readmission_summary", "length_of_stay_summary", "encounters"] | None = None,
            date_from: date | None = None, date_to: date | None = Query(None, description="whole day, inclusive"),
            sort_by: Literal["generated_at", "report_id"] = "generated_at", sort_dir: Literal["asc", "desc"] = "desc") -> dict:
    check_date_range(date_from, date_to)
    stmt = apply_filters(select(ReportRun), [ReportRun.report_type == report_type if report_type else None,
                                             *inclusive_day_range(ReportRun.generated_at, date_from, date_to, is_datetime=True)])
    page = paginate(db, apply_sort(stmt, HISTORY_SORT, sort_by, sort_dir), params,
                    lambda r: {c.name: getattr(r[0], c.name) for c in ReportRun.__table__.columns})
    return envelope(page, {"report_type": report_type, "date_from": date_from, "date_to": date_to}, sort_by, sort_dir)
