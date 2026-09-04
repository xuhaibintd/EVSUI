from __future__ import annotations

import hmac
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response


_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|pat_token|pat|api_key|access_token|authorization)"
    r"(\s*(?:=|:)\s*)([^\s,;\]\}]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def redact_sensitive_text(value: object, *, secrets: Iterable[object] = ()) -> str:
    """Return display/log-safe text without known credentials or token assignments."""

    text = str(value or "")
    for secret in secrets:
        raw = str(secret or "")
        if len(raw) >= 4:
            text = text.replace(raw, "[REDACTED]")
    text = _BEARER_TOKEN.sub("Bearer [REDACTED]", text)
    return _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )


def _origin_tuple(value: str) -> tuple[str, str, int | None] | None:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, parsed.hostname.lower(), port


def _same_origin(request: Request, candidate: str) -> bool:
    candidate_origin = _origin_tuple(candidate)
    request_origin = _origin_tuple(str(request.base_url))
    return bool(
        candidate_origin
        and request_origin
        and hmac.compare_digest(repr(candidate_origin), repr(request_origin))
    )


class SecurityMiddleware(BaseHTTPMiddleware):
    """Apply browser security headers and same-origin CSRF checks."""

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = getattr(request.app.state, "settings", None)
        csrf_enabled = bool(getattr(settings, "csrf_enabled", True))
        is_external_api = request.url.path.startswith("/api/")
        if csrf_enabled and not is_external_api and request.method.upper() in _UNSAFE_METHODS:
            fetch_site = str(request.headers.get("sec-fetch-site", "")).strip().lower()
            if fetch_site in {"cross-site", "none"}:
                return PlainTextResponse("Cross-site request rejected.", status_code=403)

            origin = str(request.headers.get("origin", "")).strip()
            referer = str(request.headers.get("referer", "")).strip()
            if origin and not _same_origin(request, origin):
                return PlainTextResponse("Cross-site request rejected.", status_code=403)
            if not origin and referer and not _same_origin(request, referer):
                return PlainTextResponse("Cross-site request rejected.", status_code=403)
            if bool(getattr(settings, "is_production", False)) and not origin and not referer:
                return PlainTextResponse("Request origin is required.", status_code=403)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        if bool(getattr(settings, "is_production", False)) and request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
