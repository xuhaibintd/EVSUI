from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import configure_error_handlers
from app.core.security import SecurityMiddleware, redact_sensitive_text


class SecurityTests(unittest.TestCase):
    def test_redaction_removes_known_secrets_and_bearer_tokens(self) -> None:
        message = "password=hunter2 pat_token:abc123 Authorization: Bearer token.value"

        redacted = redact_sensitive_text(message, secrets=("hunter2",))

        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("token.value", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_security_headers_and_cross_site_csrf_rejection(self) -> None:
        app = FastAPI()
        app.state.settings = SimpleNamespace(csrf_enabled=True, is_production=False)
        app.add_middleware(SecurityMiddleware)

        @app.get("/page")
        async def page():
            return {"ok": True}

        @app.post("/mutate")
        async def mutate():
            return {"ok": True}

        with TestClient(app) as client:
            page_response = client.get("/page")
            blocked = client.post(
                "/mutate",
                headers={"Origin": "https://attacker.example", "Sec-Fetch-Site": "cross-site"},
            )
            allowed = client.post(
                "/mutate",
                headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
            )

        self.assertEqual(page_response.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", page_response.headers["content-security-policy"])
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_production_rejects_mutation_without_origin_evidence(self) -> None:
        app = FastAPI()
        app.state.settings = SimpleNamespace(csrf_enabled=True, is_production=True)
        app.add_middleware(SecurityMiddleware)

        @app.post("/mutate")
        async def mutate():
            return {"ok": True}

        with TestClient(app) as client:
            response = client.post("/mutate")

        self.assertEqual(response.status_code, 403)

    def test_unexpected_api_error_returns_request_id_without_secret(self) -> None:
        app = FastAPI()
        configure_error_handlers(app)

        @app.get("/api/fail")
        async def fail():
            raise RuntimeError("password=should-not-leak")

        with self.assertLogs("evsui.errors", level="ERROR") as captured:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/api/fail", headers={"X-Request-ID": "req-123"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["x-request-id"], "req-123")
        self.assertEqual(response.json(), {"detail": "Internal server error", "request_id": "req-123"})
        self.assertNotIn("should-not-leak", response.text)
        self.assertNotIn("should-not-leak", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
