from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_live_connection


class LiveSmokeSafetyTests(unittest.TestCase):
    def test_explicit_live_opt_in_is_required(self):
        with mock.patch("sys.argv", ["check_live_connection.py"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                check_live_connection.main()
        self.assertEqual(error.exception.code, 2)

    def test_snapshot_timeout_and_bad_sdk_output_leave_source_unchanged_and_do_not_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.db"
            with contextlib.closing(sqlite3.connect(source_path)) as connection, connection:
                connection.execute("CREATE TABLE fixture(value TEXT)")
                connection.execute("INSERT INTO fixture VALUES('keep me')")
            baseline = source_path.read_bytes()
            for timeout in (False, True):
                with self.subTest(timeout=timeout):
                    output = io.StringIO()
                    snapshots = []

                    def run(command, **kwargs):
                        snapshot = Path(command[command.index("--snapshot-worker") + 1])
                        snapshots.append(snapshot)
                        self.assertNotEqual(snapshot, source_path)
                        with contextlib.closing(sqlite3.connect(snapshot)) as copied:
                            self.assertEqual(copied.execute("SELECT value FROM fixture").fetchone()[0], "keep me")
                        if timeout:
                            raise subprocess.TimeoutExpired(command, 1, output="sensitive-sdk-output")
                        return subprocess.CompletedProcess(command, 1, stdout="sensitive-sdk-output", stderr="secret")

                    with mock.patch.dict("os.environ", {"EVSUI_DATABASE_PATH": str(source_path), "EVSUI_ENVIRONMENT": "test"}), \
                            mock.patch("sys.argv", ["check_live_connection.py", "--read-only-live", "--timeout", "1"]), \
                            mock.patch.object(check_live_connection.subprocess, "run", side_effect=run), \
                            contextlib.redirect_stdout(output):
                        self.assertEqual(check_live_connection.main(), 1)
                    self.assertNotIn("sensitive-sdk-output", output.getvalue())
                    self.assertNotIn("secret", output.getvalue())
                    self.assertEqual(json.loads(output.getvalue())["status"], "timeout" if timeout else "failed")
                    self.assertEqual(source_path.read_bytes(), baseline)
                    self.assertTrue(snapshots)
                    self.assertTrue(all(not snapshot.parent.exists() for snapshot in snapshots))
