from __future__ import annotations

import logging
import traceback
import uuid
from html import escape

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from app.core.security import redact_sensitive_text
from app.core.form_fields import CreateFieldValidationError


logger = logging.getLogger("evsui.errors")


def _request_id(request: Request) -> str:
    supplied = str(request.headers.get("x-request-id", "")).strip()
    if supplied and len(supplied) <= 128 and all(char.isalnum() or char in "._-" for char in supplied):
        return supplied
    return uuid.uuid4().hex


def configure_error_handlers(application: FastAPI) -> None:
    """Return stable public errors while logging a redacted diagnostic trace."""

    @application.exception_handler(CreateFieldValidationError)
    async def invalid_creation_field(request: Request, exception: CreateFieldValidationError):
        if request.headers.get("HX-Request", "").lower() == "true":
            return HTMLResponse(
                f'<div class="status err" role="status">{escape(str(exception))}</div>', status_code=422,
            )
        return JSONResponse({"detail": str(exception)}, status_code=422)

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exception: Exception):
        request_id = _request_id(request)
        trace = "".join(traceback.format_exception(exception))
        logger.error(
            "Unhandled request failure request_id=%s method=%s path=%s\n%s",
            request_id,
            request.method,
            request.url.path,
            redact_sensitive_text(trace),
        )
        headers = {"X-Request-ID": request_id}
        if request.url.path.startswith("/api/"):
            return JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
                headers=headers,
            )
        return PlainTextResponse(
            f"Internal server error. Request ID: {request_id}",
            status_code=500,
            headers=headers,
        )
