from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from app.repositories.artifact_repository import ArtifactRepository


class ArtifactLifecycle:
    def __init__(self, repository: ArtifactRepository, *, root: Path) -> None:
        self.repository = repository
        self.root = Path(root).expanduser().resolve()

    def _safe_path(self, path: Path) -> Path:
        resolved = Path(path).expanduser().resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"Artifact path must stay below {self.root}.")
        return resolved

    def register_file(
        self,
        path: Path,
        *,
        kind: str,
        retention_days: int | None = None,
        hash_contents: bool = False,
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
        owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        resolved = self._safe_path(path)
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        digest = ""
        if hash_contents:
            hasher = hashlib.sha256()
            with resolved.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
        expires_at = None
        if retention_days is not None:
            expires_at = int(time.time()) + max(1, int(retention_days)) * 86400
        return self.repository.register(
            path=resolved,
            kind=kind,
            size_bytes=resolved.stat().st_size,
            sha256=digest,
            metadata=metadata,
            job_id=job_id,
            owner_user_id=owner_user_id,
            expires_at=expires_at,
        )

    def inventory(self) -> dict[str, int]:
        file_count = 0
        total_bytes = 0
        if self.root.is_dir():
            for path in self.root.rglob("*"):
                if path.is_file():
                    file_count += 1
                    total_bytes += path.stat().st_size
        tracked = self.repository.list_active(limit=10000)
        return {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "tracked_count": len(tracked),
            "tracked_bytes": sum(int(item["size_bytes"]) for item in tracked),
        }

    def cleanup_expired(self, *, apply: bool = False, now: int | None = None) -> list[dict[str, Any]]:
        candidates = self.repository.list_expired(now=now)
        results: list[dict[str, Any]] = []
        for artifact in candidates:
            try:
                path = self._safe_path(Path(artifact["path"]))
            except ValueError as ex:
                results.append({"id": artifact["id"], "status": "blocked", "detail": str(ex)})
                continue
            status = "would-delete"
            if apply:
                path.unlink(missing_ok=True)
                self.repository.mark_deleted(artifact["id"])
                status = "deleted"
            results.append({"id": artifact["id"], "path": str(path), "status": status})
        return results
