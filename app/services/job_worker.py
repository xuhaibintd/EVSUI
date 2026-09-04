from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.security import redact_sensitive_data, redact_sensitive_text, sensitive_values
from app.repositories.job_repository import JobRepository


JobHandler = Callable[[dict[str, Any], Callable[[int], None]], dict[str, Any] | None]


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
            self.repository.heartbeat(job["id"], progress=progress)

        def keep_alive() -> None:
            while not heartbeat_stop.wait(30):
                self.repository.heartbeat(job["id"], progress=progress)

        keep_alive_thread = threading.Thread(target=keep_alive, name=f"job-heartbeat-{job['id'][:8]}", daemon=True)
        keep_alive_thread.start()
        try:
            result = handler(payload, heartbeat) or {}
        except Exception as ex:
            self.repository.fail(job["id"], redact_sensitive_text(ex, secrets=sensitive_values(payload)))
        else:
            self.repository.succeed(
                job["id"],
                redact_sensitive_data(result, secrets=sensitive_values(payload)),
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
