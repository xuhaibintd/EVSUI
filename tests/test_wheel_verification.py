from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.verify_wheel import REQUIRED_RUNTIME_FILES, verify_wheel


class WheelVerificationTests(unittest.TestCase):
    def _write_wheel(self, path: Path, *extra_names: str) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            for name in sorted(REQUIRED_RUNTIME_FILES | set(extra_names)):
                archive.writestr(name, "")

    def test_current_source_files_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            wheel = Path(temporary_directory) / "application.whl"
            self._write_wheel(wheel)
            with patch("scripts.verify_wheel.expected_application_files", return_value=REQUIRED_RUNTIME_FILES):
                verify_wheel(wheel)

    def test_file_absent_from_source_is_rejected_as_stale(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            wheel = Path(temporary_directory) / "application.whl"
            self._write_wheel(wheel, "app/services/deleted_module.py")
            with patch("scripts.verify_wheel.expected_application_files", return_value=REQUIRED_RUNTIME_FILES):
                with self.assertRaisesRegex(RuntimeError, "stale or undeclared"):
                    verify_wheel(wheel)


if __name__ == "__main__":
    unittest.main()
