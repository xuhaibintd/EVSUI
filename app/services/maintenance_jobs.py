from __future__ import annotations

from typing import Any, Callable

from app.services.artifact_lifecycle import ArtifactLifecycle


ARTIFACT_CLEANUP_JOB = "artifact.cleanup"


def build_maintenance_job_handlers(
    lifecycle: ArtifactLifecycle,
    *,
    cleanup_enabled: bool,
) -> dict[str, Callable[[dict[str, Any], Callable[[int], None]], dict[str, Any]]]:
    def cleanup_artifacts(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        apply = bool(payload.get("apply"))
        if apply and not cleanup_enabled:
            raise RuntimeError("Artifact cleanup is disabled by EVSUI_ARTIFACT_CLEANUP_ENABLED.")
        heartbeat(10)
        items = lifecycle.cleanup_expired(apply=apply)
        heartbeat(90)
        return {
            "apply": apply,
            "candidate_count": len(items),
            "deleted_count": sum(1 for item in items if item.get("status") == "deleted"),
            "items": items,
        }

    return {ARTIFACT_CLEANUP_JOB: cleanup_artifacts}
