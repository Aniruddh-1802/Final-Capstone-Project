"""FastAPI application factory.  Run from src/:  uvicorn app.main:app --reload   (Swagger at /docs)."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from app.config import get_settings
from app.database import get_engine
from app.errors import register_error_handlers
from app.middleware import RequestIdMiddleware
from app.routers import admin, analytics, auth, encounters, health, patients, reference, reports
from app.security import validate_jwt_secret
from utils.logging_config import setup_logging

VITE_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
DESCRIPTION = (
    "Healthcare Patient Management System (educational capstone). Data: UCI Diabetes 130-US Hospitals 1999-2008. "
    "**Admission and discharge dates are SIMULATED** (the dataset has no dates). Readmission rates use eligible "
    "encounters (expired/hospice discharges excluded) as the denominator."
)


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build the app. Refuses to start if JWT_SECRET is missing or a placeholder. ``engine`` is injectable for tests."""
    settings = get_settings()
    validate_jwt_secret(settings.jwt_secret)
    setup_logging("app", log_dir=settings.resolve_path(settings.log_dir))
    app = FastAPI(title="Healthcare Patient Management System", version="0.1.0", description=DESCRIPTION)
    app.state.engine = engine or get_engine()
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=VITE_ORIGINS, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Request-ID"], allow_credentials=False)
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(health.router)
    for router in (patients.router, encounters.router, analytics.router, reports.router, admin.router, reference.router):
        app.include_router(router)
    logging.getLogger(__name__).info("application created")
    return app


app = create_app()

