from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_external_api_is_disabled_without_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env(project_dir=Path(tmp))

        self.assertFalse(settings.external_api_enabled)
        self.assertEqual(settings.external_api_token, "")

    def test_external_api_requires_a_token_when_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"EVSUI_EXTERNAL_API_ENABLED": "true"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "EVSUI_API_TOKEN"):
                Settings.from_env(project_dir=Path(tmp))

    def test_production_requires_an_explicit_credential_key_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"EVSUI_ENVIRONMENT": "production"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "Production requires"):
                Settings.from_env(project_dir=Path(tmp))

    def test_multiple_web_workers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"WEB_CONCURRENCY": "2"},
            clear=True,
        ):
            settings = Settings.from_env(project_dir=Path(tmp))

        with self.assertRaisesRegex(RuntimeError, "WEB_CONCURRENCY=1"):
            settings.validate_runtime()

    def test_vectorstore_poll_settings_are_validated_centrally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "EVS_VECTORSTORE_READY_TIMEOUT_SECONDS": "30",
                "EVS_VECTORSTORE_READY_POLL_SECONDS": "not-a-number",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "TIMEOUT_SECONDS must be at least 60"):
                Settings.from_env(project_dir=Path(tmp))

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {
                "EVS_VECTORSTORE_READY_TIMEOUT_SECONDS": "60",
                "EVS_VECTORSTORE_READY_POLL_SECONDS": "0.25",
            },
            clear=True,
        ):
            settings = Settings.from_env(project_dir=Path(tmp))

        self.assertEqual(settings.vectorstore_ready_timeout_seconds, 60.0)
        self.assertEqual(settings.vectorstore_ready_poll_seconds, 0.25)


if __name__ == "__main__":
    unittest.main()
