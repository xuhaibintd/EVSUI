from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app.core.runtime_manager import TeradataRuntimeManager
from app.core.settings import Settings
from app.core.single_instance import SingleInstanceLock
from app.main import create_app
from app.services.job_worker import ApplicationJobRunner


class _RuntimeManager:
    def __init__(self) -> None:
        self.entries = 0

    @asynccontextmanager
    async def operation(self):
        self.entries += 1
        yield


class _BlockingWorker:
    handlers = {"fixture": object()}

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.run_count = 0
        self.recovered_with = None

    def recover_interrupted(self, *, stale_seconds: int) -> int:
        self.recovered_with = stale_seconds
        return 0

    def run_once(self):
        self.run_count += 1
        self.started.set()
        self.release.wait(timeout=2)
        return {"id": "fixture", "kind": "fixture", "status": "succeeded"}


class _EmptyWorker:
    handlers = {"fixture": object()}

    def __init__(self) -> None:
        self.run_count = 0

    def recover_interrupted(self, *, stale_seconds: int) -> int:
        return 0

    def run_once(self):
        self.run_count += 1
        return None


class ApplicationJobRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_is_idempotent_and_stop_finishes_current_job(self):
        worker = _BlockingWorker()
        runtime = _RuntimeManager()
        runner = ApplicationJobRunner(worker, runtime, stale_seconds=120, poll_seconds=0.01)

        runner.start()
        runner.start()
        self.assertTrue(await asyncio.to_thread(worker.started.wait, 1))
        stop = asyncio.create_task(runner.stop())
        await asyncio.sleep(0.01)
        self.assertFalse(stop.done())

        worker.release.set()
        await asyncio.wait_for(stop, timeout=1)

        self.assertFalse(runner.running)
        self.assertEqual(worker.recovered_with, 120)
        self.assertEqual(worker.run_count, 1)
        self.assertEqual(runtime.entries, 1)

    async def test_stop_while_waiting_for_runtime_does_not_claim_a_job(self):
        runtime = TeradataRuntimeManager()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def hold_runtime():
            async with runtime.operation():
                entered.set()
                await release.wait()

        holder = asyncio.create_task(hold_runtime())
        await entered.wait()
        worker = _EmptyWorker()
        runner = ApplicationJobRunner(worker, runtime, stale_seconds=120, poll_seconds=0.01)
        runner.start()
        await asyncio.sleep(0.01)
        stopping = asyncio.create_task(runner.stop())
        await asyncio.sleep(0.01)

        release.set()
        await holder
        await asyncio.wait_for(stopping, timeout=1)

        self.assertEqual(worker.run_count, 0)


class ApplicationLifespanTests(unittest.TestCase):
    def test_web_application_starts_and_stops_background_jobs_automatically(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            "os.environ",
            {
                "EVSUI_ENVIRONMENT": "development",
                "EVSUI_DATABASE_PATH": str(Path(directory) / "app.db"),
                "EVSUI_CREDENTIAL_KEY_FILE": str(Path(directory) / "credentials.key"),
                "EVSUI_EXTERNAL_API_ENABLED": "false",
            },
            clear=True,
        ), mock.patch("app.web_support._load_auth_users", return_value={}), mock.patch(
            "app.web_support._load_connect_defaults", return_value={}
        ):
            application = create_app(Settings.from_env(project_dir=Path(directory)))
            with TestClient(application) as client:
                runner = application.state.background_job_runner
                self.assertTrue(runner.running)
                self.assertEqual(client.get("/healthz").status_code, 200)
                with self.assertRaisesRegex(RuntimeError, "Another teradataevsui process"):
                    with SingleInstanceLock(application.state.settings.database_path.with_suffix(".app.lock")):
                        pass
            self.assertFalse(runner.running)
            with SingleInstanceLock(application.state.settings.database_path.with_suffix(".app.lock")):
                pass


if __name__ == "__main__":
    unittest.main()
