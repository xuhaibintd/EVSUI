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


if __name__ == "__main__":
    unittest.main()
