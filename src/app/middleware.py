"""Request-id middleware: one id per request, returned in X-Request-ID and attached to every log line."""
from __future__ import annotations

import logging
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from utils.request_context import request_id_var

log = logging.getLogger(__name__)


class RequestIdMiddleware:
    """Pure ASGI middleware; also writes one access-log line (method, path, status, duration - no query/body)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        request_id_var.set(request_id)  # deliberately not reset: outer error handlers still need it
        scope.setdefault("state", {})["request_id"] = request_id
        started, status = time.perf_counter(), 500

        async def send_with_header(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            log.info("%s %s -> %d (%.1f ms)", scope["method"], scope["path"], status,
                     (time.perf_counter() - started) * 1000)
