from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.auth_store import AuthStore
from app.session_state import SessionAwareState, new_session_scope


class AuthStoreTests(unittest.TestCase):
    def _store(self, directory: str, name: str = "auth.db") -> AuthStore:
        store = AuthStore(Path(directory) / name, session_ttl_seconds=600)
        store.initialize()
        return store

    def test_user_password_and_server_session_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            created = store.create_user(
                username="admin",
                password="strong-password",
                role="admin",
            )

            self.assertIsNone(store.authenticate("admin", "wrong-password"))
            principal = store.authenticate("admin", "strong-password")
            self.assertIsNotNone(principal)
            self.assertEqual(principal.role, "admin")

            session_id = store.create_session(created)
            self.assertEqual(store.get_session(session_id).username, "admin")
            store.revoke_session(session_id)
            self.assertIsNone(store.get_session(session_id))

    def test_export_import_preserves_argon2_hashes_and_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = self._store(tmpdir, "source.db")
            source.create_user(username="admin", password="strong-password", role="admin")
            source.create_user(username="reader", password="reader-password", role="viewer")
            payload = source.export_users()

            self.assertNotIn("strong-password", str(payload))
            self.assertTrue(payload["users"][0]["password_hash"].startswith("$argon2"))

            target = self._store(tmpdir, "target.db")
            self.assertEqual(target.import_users(payload), 2)
            self.assertEqual(target.authenticate("reader", "reader-password").role, "viewer")

    def test_last_enabled_admin_cannot_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            store.create_user(username="admin", password="strong-password", role="admin")

            with self.assertRaisesRegex(ValueError, "last enabled administrator"):
                store.set_enabled("admin", False)
            with self.assertRaisesRegex(ValueError, "last enabled administrator"):
                store.set_role("admin", "viewer")


class SessionAwareStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_tasks_keep_independent_ui_state(self) -> None:
        state = SessionAwareState()
        scope_a = new_session_scope("alice", lambda: {"value": "a"}, dict)
        scope_b = new_session_scope("bob", lambda: {"value": "b"}, dict)

        async def update(scope: dict, value: str) -> str:
            state.activate_session_scope(scope)
            state.evs_state["value"] = value
            await asyncio.sleep(0)
            return state.evs_state["value"]

        values = await asyncio.gather(update(scope_a, "alice"), update(scope_b, "bob"))

        self.assertEqual(values, ["alice", "bob"])
        self.assertEqual(scope_a["evs_state"]["value"], "alice")
        self.assertEqual(scope_b["evs_state"]["value"], "bob")


if __name__ == "__main__":
    unittest.main()
