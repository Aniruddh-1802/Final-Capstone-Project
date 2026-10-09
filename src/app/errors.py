"""Uniform error contract: {"error": {"code": str, "message": str, "details": any}} for every error response."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from utils.request_context import request_id_var

log = logging.getLogger(__name__)
STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed",
                409: "conflict", 422: "validation_error", 429: "too_many_requests"}


class ApiError(Exception):
    """Raise anywhere in the API to return the uniform error body with a chosen status and code."""

    def __init__(self, status_code: int, code: str, message: str, details: Any = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message, self.details, self.headers = status_code, code, message, details, headers


def error_response(status_code: int, code: str, message: str, details: Any = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    """Build the contract response; X-Request-ID is always present (also for errors raised outside the middleware)."""
    out = {"X-Request-ID": request_id_var.get(), **(headers or {})}
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status_code,
                        headers=out)


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = STATUS_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, message, None, getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Only location, message and type: never echo the submitted input (it may hold a password).
    details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
    return error_response(422, "validation_error", "Request validation failed", details)


async def _database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    log.error("database error on %s %s: %s", request.method, request.url.path, type(exc).__name__, exc_info=exc)
    return error_response(500, "database_error", "A database error occurred")


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__, exc_info=exc)
    return error_response(500, "internal_error", "An internal error occurred")


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers so 401/403/404/405/409/422/500 all share one JSON shape and never leak SQL."""
    app.add_exception_handler(ApiError, _api_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, _database_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled)
