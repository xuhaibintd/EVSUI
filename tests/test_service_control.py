from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.core.process_lock import ProcessLock, lock_is_held
from app.core.settings import Settings
from app.worker import run_worker

ROOT = Path(__file__).resolve().parents[1]


class WorkerShutdownTests(unittest.TestCase):
    def test_stop_finishes_current_job_without_claiming_next(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {
            "EVSUI_DATABASE_PATH": str(Path(directory) / "app.db"), "EVSUI_ENVIRONMENT": "test",
        }):
            settings = Settings.from_env(project_dir=Path(directory))
            stop = threading.Event()
            worker = mock.Mock()
            worker.recover_interrupted.return_value = 0
            worker.handlers = {"fixture": object()}

            def finish_current():
                stop.set()
                return {"id": "fixture", "kind": "fixture", "status": "succeeded"}

            worker.run_once.side_effect = finish_current
            with mock.patch("app.worker.build_worker", return_value=worker):
                self.assertEqual(run_worker(settings, stop), 0)
            worker.run_once.assert_called_once()
            self.assertFalse(lock_is_held(settings.database_path.with_suffix(".worker.lock")))

    def test_second_worker_refused_before_initialization(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict("os.environ", {
            "EVSUI_DATABASE_PATH": str(Path(directory) / "app.db"), "EVSUI_ENVIRONMENT": "test",
        }):
            settings = Settings.from_env(project_dir=Path(directory))
            with ProcessLock(settings.database_path.with_suffix(".worker.lock")), mock.patch("app.worker.build_worker") as build:
                with self.assertRaisesRegex(RuntimeError, "Another process"):
                    run_worker(settings, threading.Event())
                build.assert_not_called()


class ServiceControlIntegrationTests(unittest.TestCase):
    """Real child processes, isolated source checkout, no credentials or business data."""

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="evsui lifecycle ")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.project = Path(cls.temporary.name) / "project with spaces"
        shutil.copytree(ROOT / "app", cls.project / "app", ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "auth_users.json", "local_dev.json", "unstructured.json", "unstructured_models.json",
        ))
        shutil.copytree(ROOT / "scripts", cls.project / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def setUp(self):
        self.runtime = Path(tempfile.mkdtemp(dir=self.temporary.name, prefix="runtime "))
        self.state = self.runtime / "state"
        self.env = {**os.environ, "EVSUI_ENVIRONMENT": "test", "WEB_CONCURRENCY": "1",
                    "EVSUI_DATABASE_PATH": str(self.runtime / "data.db"),
                    "EVSUI_CREDENTIAL_KEY_FILE": str(self.runtime / "credentials.key"),
                    "EVSUI_CREDENTIAL_KEY": "", "EVSUI_EXTERNAL_API_ENABLED": "false",
                    "EVSUI_BOOTSTRAP_ADMIN": "", "EVSUI_BOOTSTRAP_PASSWORD": ""}
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.addCleanup(lambda: self.control("stop", timeout=30, expected=None))

    def control(self, action, *, extra=(), expected=0, timeout=30, env=None):
        result = subprocess.run([sys.executable, str(self.project / "scripts" / "service_control.py"), action,
                                 "--state-dir", str(self.state), "--port", str(self.port),
                                 "--timeout", str(timeout), *extra],
                                env=env or self.env, cwd=self.runtime, capture_output=True, text=True, timeout=timeout * 2 + 15)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr + self.logs())
        return result

    def logs(self):
        return "\n".join(path.read_text(encoding="utf-8", errors="replace")[-2500:]
                         for path in (self.state / "logs").glob("*.log"))

    def record(self, component):
        return json.loads((self.state / f"{component}.json").read_text(encoding="utf-8"))

    def test_start_status_idempotency_restart_stop_and_stale_pid_safety(self):
        self.control("start")
        web = self.record("web")
        worker = self.record("worker")
        self.assertIn("web: running", self.control("status").stdout)
        self.control("start")
        self.assertEqual(self.record("web")["token"], web["token"])
        self.assertEqual(self.record("worker")["token"], worker["token"])
        self.control("restart")
        self.assertNotEqual(self.record("web")["token"], web["token"])
        self.control("stop")
        self.control("stop")
        self.assertIn("worker: stopped", self.control("status").stdout)
        # A recycled/stale PID may refer to this test runner. Stop must not signal it.
        web["pid"] = os.getpid()
        web["status"] = "running"
        (self.state / "web.json").write_text(json.dumps(web), encoding="utf-8")
        self.control("stop")
        self.assertIn("web: stopped", self.control("status").stdout)

    def test_occupied_port_does_not_start_worker_or_touch_listener(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", self.port))
            listener.listen()
            result = self.control("start", expected=1)
            self.assertIn("occupied", result.stderr)
            self.assertEqual(listener.getsockname()[1], self.port)
            self.assertFalse((self.state / "worker.json").exists())

    def test_single_components_and_environment_mismatch(self):
        self.control("start", extra=("--component", "web"))
        self.assertFalse((self.state / "worker.json").exists())
        different = {**self.env, "EVSUI_DATABASE_PATH": str(self.runtime / "other.db")}
        result = self.control("start", extra=("--component", "worker"), env=different, expected=1)
        self.assertIn("different settings", result.stderr)
        self.control("start", extra=("--component", "worker"))
        self.control("stop", extra=("--component", "worker"))
        self.assertIn("web: running", self.control("status").stdout)

    def test_start_failure_rolls_back_only_new_services(self):
        # A startup timeout is a stop request, never an orphaned background worker.
        result = self.control("start", timeout=0.001, expected=1)
        self.assertIn("timed out", result.stderr)
        # Child may still be importing; its token-specific stop request persists.
        import time
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if (self.state / "web.json").exists() and self.record("web")["status"] in {"stopped", "failed"}:
                break
            time.sleep(0.1)
        else:
            self.fail("Timed-out startup did not stop: " + self.logs())
        self.control("stop")  # Also wait for interpreter/virtualenv launcher exit.
        self.control("start")
        self.assertIn("worker: running", self.control("status").stdout)

    def test_worker_start_failure_preserves_preexisting_web(self):
        worker_source = self.project / "app" / "worker.py"
        original = worker_source.read_text(encoding="utf-8")
        self.addCleanup(worker_source.write_text, original, encoding="utf-8")
        worker_source.write_text(original + '\n\ndef build_worker(settings):\n    raise RuntimeError("fixture startup failure")\n', encoding="utf-8")
        self.control("start", expected=1)
        self.control("stop")  # Wait for rollback to drain the newly started web.
        self.control("start", extra=("--component", "web"))
        token = self.record("web")["token"]
        self.control("start", expected=1)
        self.assertEqual(self.record("web")["token"], token)
        self.assertIn("web: running", self.control("status").stdout)

    def test_stop_timeout_drains_current_job_and_leaves_next_queued(self):
        import time
        from app.auth_store import AuthStore

        worker_source = self.project / "app" / "worker.py"
        original = worker_source.read_text(encoding="utf-8")
        self.addCleanup(worker_source.write_text, original, encoding="utf-8")
        worker_source.write_text(original + '''

_fixture_original_builder = build_worker
def _fixture_handler(payload, heartbeat):
    import time
    from pathlib import Path
    while not Path(payload['release']).exists():
        time.sleep(0.05)
    return {'completed': True}

def build_worker(settings):
    worker = _fixture_original_builder(settings)
    worker.handlers['fixture.block'] = _fixture_handler
    return worker
''', encoding="utf-8")
        release = self.runtime / "release"
        self.addCleanup(release.write_text, "release", encoding="utf-8")
        self.control("start", extra=("--component", "worker"))
        store = AuthStore(Path(self.env["EVSUI_DATABASE_PATH"]))
        first = store.jobs.create(kind="fixture.block", payload={"release": str(release)})
        deadline = time.monotonic() + 10
        while store.jobs.get(first["id"])["status"] != "running" and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertEqual(store.jobs.get(first["id"])["status"], "running")
        second = store.jobs.create(kind="fixture.block", payload={"release": str(release)})
        result = self.control("stop", timeout=0.5, expected=2)
        self.assertIn("Nothing was force-killed", result.stdout)
        self.assertEqual(store.jobs.get(first["id"])["status"], "running")
        release.write_text("release", encoding="utf-8")
        self.control("stop")
        self.assertEqual(store.jobs.get(first["id"])["status"], "succeeded")
        self.assertEqual(store.jobs.get(second["id"])["status"], "queued")
