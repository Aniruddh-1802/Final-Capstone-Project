"""GET /health: database status plus the latest pipeline run. Public (no token) and free of sensitive data."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import PipelineRun

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _run_summary(run: PipelineRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.run_id, "source_file": run.source_file, "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "rows_read": run.rows_read, "rows_loaded": run.rows_loaded, "rows_rejected": run.rows_rejected,
        "rows_skipped_existing": run.rows_skipped_existing,
    }


@router.get("/health", summary="Service and database status")
def health(request: Request) -> JSONResponse:
    """200 when the database answers; 503 'degraded' when it does not (no SQL or host details in the body)."""
    try:
        with Session(request.app.state.engine) as session:
            session.execute(text("SELECT 1"))
            latest = session.scalar(select(PipelineRun).order_by(PipelineRun.run_id.desc()).limit(1))
            body = {"status": "ok", "database": "up", "latest_pipeline_run": _run_summary(latest)}
        return JSONResponse(body)
    except SQLAlchemyError as exc:
        log.error("health check failed: %s", type(exc).__name__)
        return JSONResponse({"status": "degraded", "database": "down", "latest_pipeline_run": None}, status_code=503)
