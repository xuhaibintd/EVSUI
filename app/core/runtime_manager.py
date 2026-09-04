from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

from app.core.security import redact_sensitive_text


class TeradataRuntimeManager:
    """Serialize access to the process-global Teradata SDK context."""

    def __init__(self) -> None:
        self._async_lock = asyncio.Lock()
        self._thread_lock = threading.RLock()
        self.active_identity = ""
        self.generation = 0

    @asynccontextmanager
    async def operation(self):
        async with self._async_lock:
            yield

    def reactivate(
        self,
        *,
        identity: str,
        cleanup: Callable[[], object],
        connect: Callable[[], object],
        authenticate: Callable[[], object],
    ) -> None:
        with self._thread_lock:
            cleanup()
            self.active_identity = ""
            try:
                connect()
                authenticate()
            except Exception:
                cleanup()
                raise
            self.active_identity = str(identity or "")
            self.generation += 1

    def mark_active(self, identity: str) -> None:
        with self._thread_lock:
            self.active_identity = str(identity or "")
            self.generation += 1

    def invalidate(self) -> None:
        with self._thread_lock:
            self.active_identity = ""


class RuntimeIsolationMiddleware(BaseHTTPMiddleware):
    """Keep process-global SDK state from crossing concurrent HTTP sessions."""

    async def dispatch(self, request: Request, call_next) -> Response:
        manager = getattr(request.app.state, "teradata_runtime_manager", None)
        path = request.url.path
        if manager is None or not (path.startswith("/ui/") or path.startswith("/api/bookrag")):
            return await call_next(request)

        async with manager.operation():
            if path.startswith("/ui/") and path not in {"/ui/evs/connect", "/ui/evs/reset"}:
                ensure_runtime = getattr(request.app.state, "ensure_session_runtime", None)
                auth_store = getattr(request.app.state, "auth_store", None)
                session_id = str(request.cookies.get("evsui_sid", "")).strip()
                principal = auth_store.get_session(session_id, touch=False) if auth_store and session_id else None
                if principal is not None and callable(ensure_runtime):
                    activate_scope = getattr(request.app.state, "activate_session_scope", None)
                    scope = request.app.state.user_sessions.get(session_id)
                    if scope is not None and callable(activate_scope):
                        activate_scope(scope)
                    state = (scope or {}).get("evs_state", {})
                    if state.get("connected"):
                        try:
                            ensure_runtime(request, request.app)
                        except Exception as ex:
                            safe_error = redact_sensitive_text(
                                ex,
                                secrets=(
                                    (state.get("params") or {}).get("password"),
                                    (state.get("params") or {}).get("pat_token"),
                                ),
                            )
                            state["connected"] = False
                            state["last_success"] = ""
                            state["last_error"] = f"Teradata runtime activation failed: {safe_error}"
                            manager.invalidate()
                            return PlainTextResponse(state["last_error"], status_code=409)
            return await call_next(request)
