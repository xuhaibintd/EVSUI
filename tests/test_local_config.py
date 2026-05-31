from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.local_config import local_auth_users, local_connection_defaults, local_login_defaults, local_unstructured_defaults
from app.services.unstructured_runtime import _load_unstructured_runtime_config
from app.session_state import activate_session_state, load_connect_defaults


class LocalConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_config = os.environ.get("EVSUI_LOCAL_CONFIG")

    def tearDown(self) -> None:
        if self._original_config is None:
            os.environ.pop("EVSUI_LOCAL_CONFIG", None)
        else:
            os.environ["EVSUI_LOCAL_CONFIG"] = self._original_config

    def _write_config(self, payload: dict) -> Path:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        with handle:
            json.dump(payload, handle)
        path = Path(handle.name)
        os.environ["EVSUI_LOCAL_CONFIG"] = str(path)
        return path

    def test_local_defaults_are_empty_when_config_is_missing(self) -> None:
        os.environ["EVSUI_LOCAL_CONFIG"] = str(Path(tempfile.gettempdir()) / "evsui-missing-local-config.json")

        self.assertEqual(local_login_defaults(), ("", ""))
        self.assertEqual(local_auth_users(), {})
        self.assertEqual(
            local_connection_defaults(),
            {
                "host": "",
                "username": "",
                "password": "",
                "ues_url": "",
                "pat_token": "",
                "pem_file": "",
            },
        )
        self.assertEqual(local_unstructured_defaults(), {})

    def test_local_defaults_are_loaded_from_config(self) -> None:
        self._write_config(
            {
                "login": {
                    "username": "admin",
                    "password": "pw",
                    "users": {"debug": "secret"},
                },
                "connection": {
                    "host": "db.example.com",
                    "username": "db_user",
                    "password": "db_pw",
                    "ues_url": "https://example.com/open-analytics",
                    "pat_token": "pat",
                    "pem_file": "uploads\\pem\\debug.pem",
                },
                "unstructured": {
                    "api_key": "unstructured-key",
                    "api_url": "https://platform.unstructuredapp.io/api/v1",
                },
            }
        )

        self.assertEqual(local_login_defaults(), ("admin", "pw"))
        self.assertEqual(local_auth_users(), {"debug": "secret", "admin": "pw"})
        self.assertEqual(local_connection_defaults()["host"], "db.example.com")
        self.assertEqual(local_connection_defaults()["pat_token"], "pat")
        self.assertEqual(local_unstructured_defaults()["api_key"], "unstructured-key")

    def test_unstructured_runtime_prefers_session_overrides(self) -> None:
        self._write_config(
            {
                "unstructured": {
                    "api_key": "config-key",
                    "api_url": "https://config.example/api",
                },
            }
        )

        api_key, api_url = _load_unstructured_runtime_config(
            {
                "unstructured_api_key": "session-key",
                "unstructured_api_url": "https://session.example/api",
            }
        )

        self.assertEqual(api_key, "session-key")
        self.assertEqual(api_url, "https://session.example/api")

    def test_missing_configured_pem_path_falls_back_to_latest_upload(self) -> None:
        self._write_config(
            {
                "connection": {
                    "host": "db.example.com",
                    "username": "db_user",
                    "password": "db_pw",
                    "pem_file": "uploads\\pem\\missing.pem",
                },
            }
        )

        defaults = load_connect_defaults(
            latest_uploaded_pem_relative=lambda: "uploads\\pem\\latest.pem",
            vs_basics_dir=Path(tempfile.gettempdir()),
            default_pat_token="",
        )

        self.assertEqual(defaults["pem_file"], "uploads\\pem\\latest.pem")

    def test_existing_disconnected_session_refreshes_stale_pem_only(self) -> None:
        state = {
            "connected": False,
            "params": {
                "host": "typed-host",
                "username": "",
                "password": "",
                "ues_url": "",
                "pat_token": "",
                "pem_file": "uploads\\pem\\missing.pem",
            },
        }
        request = SimpleNamespace(cookies={"evsui_sid": "sid-1", "evsui_user": "admin"})
        app = SimpleNamespace(
            state=SimpleNamespace(
                user_sessions={
                    "sid-1": {
                        "evs_state": state,
                        "create_form_values": {},
                        "last_create_operation": None,
                        "document_uploads": [],
                        "document_upload_notices": [],
                        "chat_history": [],
                    }
                }
            )
        )

        activate_session_state(
            request,
            app,
            "evsui_sid",
            default_evs_state_fn=lambda: {
                "params": {
                    "host": "default-host",
                    "username": "default-user",
                    "password": "default-password",
                    "ues_url": "default-url",
                    "pat_token": "default-token",
                    "pem_file": "uploads\\pem\\valid.pem",
                    "unstructured_api_url": "https://default-unstructured.example/api",
                    "unstructured_api_key": "default-unstructured-key",
                }
            },
            default_create_values_fn=dict,
        )

        self.assertEqual(app.state.evs_state["params"]["host"], "typed-host")
        self.assertEqual(app.state.evs_state["params"]["username"], "default-user")
        self.assertEqual(app.state.evs_state["params"]["pem_file"], "uploads\\pem\\valid.pem")
        self.assertEqual(app.state.evs_state["params"]["unstructured_api_url"], "https://default-unstructured.example/api")
        self.assertEqual(app.state.evs_state["params"]["unstructured_api_key"], "default-unstructured-key")


if __name__ == "__main__":
    unittest.main()
