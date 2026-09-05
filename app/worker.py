from __future__ import annotations

import argparse
import logging
import signal
import threading

from app.auth_store import AuthStore
from app.core.settings import Settings
from app.core.process_lock import ProcessLock
from app.services.artifact_lifecycle import ArtifactLifecycle
from app.services.job_worker import PersistentJobWorker
from app.services.maintenance_jobs import build_maintenance_job_handlers
from app.services.workflow_jobs import build_workflow_job_handlers


logger = logging.getLogger("evsui.worker")


def build_worker(settings: Settings) -> PersistentJobWorker:
    auth_store = AuthStore(
        settings.database_path,
        session_ttl_seconds=settings.session_ttl_seconds,
        pem_runtime_dir=settings.project_dir / "pem_runtime",
        legacy_file_root=settings.project_dir,
        credential_key=settings.credential_key,
        credential_key_file=settings.credential_key_file,
        allow_generated_credential_key=not settings.is_production,
    )
    auth_store.initialize()
    if settings.is_production:
        auth_store.credential_vault.cipher()
    lifecycle = ArtifactLifecycle(auth_store.artifacts, root=settings.project_dir / "uploads")
    handlers = build_workflow_job_handlers(
        auth_store,
        artifact_lifecycle=lifecycle,
        artifact_retention_days=settings.artifact_retention_days,
        vectorstore_ready_timeout_seconds=settings.vectorstore_ready_timeout_seconds,
        vectorstore_ready_poll_seconds=settings.vectorstore_ready_poll_seconds,
    )
    handlers.update(
        build_maintenance_job_handlers(
            lifecycle,
            cleanup_enabled=settings.artifact_cleanup_enabled,
        )
    )
    return PersistentJobWorker(auth_store.jobs, handlers=handlers)


def run_worker(settings: Settings, stop: threading.Event, *, once: bool = False,
               max_jobs: int = 100, poll_seconds: float = 1.0, on_ready=None) -> int:
    """Drain the current job on stop; guard manual and managed workers alike."""
    with ProcessLock(settings.database_path.with_suffix(".worker.lock")):
        worker = build_worker(settings)
        recovered = worker.recover_interrupted(stale_seconds=settings.job_stale_seconds)
        if recovered:
            logger.warning("Recovered %s interrupted job(s).", recovered)
        if on_ready is not None:
            on_ready()
        logger.info("Worker started with %s registered handler(s).", len(worker.handlers))
        completed_count = 0
        while not stop.is_set():
            completed = worker.run_once()
            if completed is None:
                if once:
                    break
                stop.wait(max(0.1, poll_seconds))
            else:
                completed_count += 1
                logger.info("Job %s (%s) finished with status %s.",
                            completed["id"], completed["kind"], completed["status"])
                if once and completed_count >= max(1, max_jobs):
                    break
        logger.info("Worker stopped after processing %s job(s).", completed_count)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the teradataevsui durable workflow worker.")
    parser.add_argument("--once", action="store_true", help="Drain currently queued work and exit.")
    parser.add_argument("--max-jobs", type=int, default=100)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings.from_env()
    stop = threading.Event()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return run_worker(settings, stop, once=args.once, max_jobs=args.max_jobs, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
