from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.security import redact_sensitive_data, redact_sensitive_text, sensitive_values
from app.repositories.job_repository import JobRepository


JobHandler = Callable[[dict[str, Any], Callable[[int], None]], dict[str, Any] | None]
logger = logging.getLogger("evsui.jobs")


class JobExecutionError(RuntimeError):
    """A failed workflow may still have per-file results worth showing to its owner."""

    def __init__(self, message: str, *, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = result


class JobClaimLost(RuntimeError):
    pass


def _deep_merge(target: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(target)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif isinstance(value, list) and isinstance(merged.get(key), list):
            target_items = list(merged[key])
            for index, overlay_item in enumerate(value):
                if overlay_item is None:
                    continue
                if index >= len(target_items):
                    target_items.append(overlay_item)
                elif isinstance(overlay_item, dict) and isinstance(target_items[index], dict):
                    target_items[index] = _deep_merge(target_items[index], overlay_item)
                else:
                    target_items[index] = overlay_item
            merged[key] = target_items
        else:
            merged[key] = value
    return merged


@dataclass
class PersistentJobWorker:
    repository: JobRepository
    handlers: dict[str, JobHandler]

    def run_once(self) -> dict[str, Any] | None:
        job = self.repository.claim_next(kinds=set(self.handlers))
        if job is None:
            return None
        if job["status"] != "running":
            return job
        handler = self.handlers[job["kind"]]
        payload = _deep_merge(job["payload"], job.get("secret_payload") or {})
        payload["_job"] = {
            "id": job["id"],
            "owner_user_id": job.get("owner_user_id"),
            "connection_profile_id": job.get("connection_profile_id"),
            "attempt": job.get("attempt", 0),
        }
        progress = 1
        heartbeat_stop = threading.Event()

        def heartbeat(value: int) -> None:
            nonlocal progress
            progress = max(0, min(int(value), 99))
            if not self.repository.heartbeat(job["id"], progress=progress, expected_attempt=job["attempt"]):
                raise JobClaimLost("The job was recovered by another job runner.")

        def keep_alive() -> None:
            while not heartbeat_stop.wait(30):
                if not self.repository.heartbeat(job["id"], progress=progress, expected_attempt=job["attempt"]):
                    return

        keep_alive_thread = threading.Thread(target=keep_alive, name=f"job-heartbeat-{job['id'][:8]}", daemon=True)
        keep_alive_thread.start()
        try:
            result = handler(payload, heartbeat) or {}
        except JobClaimLost:
            pass
        except Exception as ex:
            self.repository.fail(
                job["id"], redact_sensitive_text(ex, secrets=sensitive_values(payload)),
                result=redact_sensitive_data(ex.result, secrets=sensitive_values(payload))
                if isinstance(ex, JobExecutionError) else None,
                expected_attempt=job["attempt"],
            )
        else:
            self.repository.succeed(
                job["id"],
                redact_sensitive_data(result, secrets=sensitive_values(payload)),
                expected_attempt=job["attempt"],
            )
        finally:
            heartbeat_stop.set()
            keep_alive_thread.join(timeout=1)
        return self.repository.get(job["id"])

    def recover_interrupted(self, *, stale_seconds: int) -> int:
        return self.repository.recover_stale(stale_before=int(time.time()) - max(60, int(stale_seconds)))

    def run_until_empty(self, *, max_jobs: int = 100) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        for _ in range(max(1, int(max_jobs))):
            job = self.run_once()
            if job is None:
                break
            completed.append(job)
        return completed


@dataclass
class ApplicationJobRunner:
    """Run durable jobs inside the single FastAPI process."""

    worker: PersistentJobWorker
    runtime_manager: Any
    stale_seconds: int
    poll_seconds: float = 1.0
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task | None = field(default=None, init=False)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        recovered = self.worker.recover_interrupted(stale_seconds=self.stale_seconds)
        if recovered:
            logger.warning("Recovered %s interrupted job(s).", recovered)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="teradataevsui-jobs")
        logger.info("Background job runner started with %s handler(s).", len(self.worker.handlers))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None
        logger.info("Background job runner stopped.")

    async def _run(self) -> None:
        recovery_interval = min(60.0, max(1.0, self.stale_seconds / 2))
        next_recovery = time.monotonic() + recovery_interval
        while not self._stop.is_set():
            try:
                # The SDK context is process-global. Reuse the same lock as HTTP
                # operations so a background job cannot replace an active session.
                async with self.runtime_manager.operation():
                    if self._stop.is_set():
                        break
                    completed = await asyncio.to_thread(self.worker.run_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background job polling failed; retrying.")
                completed = None
            if completed is not None:
                logger.info(
                    "Job %s (%s) finished with status %s.",
                    completed["id"],
                    completed["kind"],
                    completed["status"],
                )
                continue
            if time.monotonic() >= next_recovery:
                recovered = self.worker.recover_interrupted(stale_seconds=self.stale_seconds)
                next_recovery = time.monotonic() + recovery_interval
                if recovered:
                    logger.warning("Recovered %s interrupted job(s).", recovered)
                    continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.1, self.poll_seconds))
            except TimeoutError:
                pass
