from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "testnova_request_id",
    default="-",
)

_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(authorization|password|api[_-]?key|secret|token)"
    r"(\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = _SENSITIVE_VALUE.sub(r"\1\2[REDACTED]", record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created,
                timezone.utc,
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "request_id": request_id_context.get(),
        }
        error_type = getattr(record, "error_type", None)
        if error_type:
            payload["error_type"] = str(error_type)
        return json.dumps(payload, ensure_ascii=True)


def configure_structured_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        # Uvicorn/dev consoles commonly capture stdout as their primary stream.
        # Make the structured application diagnostics visible there explicitly.
        root.addHandler(logging.StreamHandler(sys.stdout))
    for handler in root.handlers:
        handler.setFormatter(JsonLogFormatter())


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = logging.getLogger("testnova.request")

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500
        path = scope.get("path", "")

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            self.logger.info(
                "HTTP request completed: method=%s path=%s status=%s duration_ms=%.2f",
                scope.get("method", ""),
                path,
                status_code,
                (time.perf_counter() - started) * 1000,
            )
            request_id_context.reset(token)
