from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.auth_store import AuthStore
from app.routers.web import router as web_router
from app.runtime import STATIC_DIR, TEMPLATES_DIR
from app.web_support import initialize_app_state


class UserAdminRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        app = FastAPI()
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
        initialize_app_state(app, Jinja2Templates(directory=str(TEMPLATES_DIR)))
        store = AuthStore(Path(self.tempdir.name) / "users.db", session_ttl_seconds=600)
        store.initialize()
        store.create_user(username="admin", password="admin-password", role="admin")
        store.create_user(username="reader", password="reader-password", role="viewer")
        app.state.auth_store = store
        app.state.user_sessions = {}
        app.include_router(web_router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.tempdir.cleanup()

    def _login(self, username: str, password: str) -> None:
        response = self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("evsui_sid", response.cookies)

    def test_admin_can_create_and_export_users(self) -> None:
        self._login("admin", "admin-password")

        page = self.client.get("/admin/users")
        self.assertEqual(page.status_code, 200)
        self.assertIn("User Management", page.text)

        created = self.client.post(
            "/admin/users/create",
            data={
                "username": "operator",
                "display_name": "Operator",
                "password": "operator-password",
                "role": "operator",
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertIn("operator", created.text)
        self.assertIn("created", created.text)

        exported = self.client.get("/admin/users/export")
        self.assertEqual(exported.status_code, 200)
        self.assertNotIn("operator-password", exported.text)
        self.assertIn("$argon2", exported.text)

    def test_viewer_cannot_open_user_admin(self) -> None:
        self._login("reader", "reader-password")

        response = self.client.get("/admin/users")

        self.assertEqual(response.status_code, 403)

    def test_forged_legacy_cookies_do_not_authenticate(self) -> None:
        self.client.cookies.set("evsui_auth", "1")
        self.client.cookies.set("evsui_user", "admin")
        self.client.cookies.set("evsui_sid", "forged")

        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")


if __name__ == "__main__":
    unittest.main()
