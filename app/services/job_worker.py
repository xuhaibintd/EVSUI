from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.security import redact_sensitive_text
from app.repositories.job_repository import JobRepository


JobHandler = Callable[[dict[str, Any], Callable[[int], None]], dict[str, Any] | None]


@dataclass
class PersistentJobWorker:
    repository: JobRepository
    handlers: dict[str, JobHandler]

    def run_once(self) -> dict[str, Any] | None:
        job = self.repository.claim_next(kinds=set(self.handlers))
        if job is None:
            return None
        handler = self.handlers[job["kind"]]
        heartbeat = lambda progress: self.repository.heartbeat(job["id"], progress=progress)
        try:
            result = handler(job["payload"], heartbeat) or {}
        except Exception as ex:
            self.repository.fail(job["id"], redact_sensitive_text(ex))
        else:
            self.repository.succeed(job["id"], result)
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
