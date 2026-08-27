from __future__ import annotations

from pathlib import Path
from typing import Any

from app.integrations.unstructured.contracts import validate_workflow_nodes
from app.services.unstructured_job_runner import (
    create_unstructured_client,
    enforce_unstructured_job_submission_spacing,
    run_unstructured_workflow_job_for_file,
)


def create_client(*, api_key: str, api_url: str, timeout_ms: int | None = None):
    return create_unstructured_client(api_key=api_key, api_url=api_url, timeout_ms=timeout_ms)


def space_job_submissions(last_submitted_at: float | None, *, minimum_spacing_seconds: float = 1.35) -> float:
    return enforce_unstructured_job_submission_spacing(
        last_submitted_at,
        minimum_spacing_seconds=minimum_spacing_seconds,
    )


def run_workflow_for_file(
    client,
    *,
    request_parameters: dict[str, Any],
    src: Path,
    timeout_seconds: int,
    poll_interval_seconds: int,
    api_key: str,
    api_url: str,
):
    validate_workflow_nodes(list(request_parameters.get("workflow_nodes") or []))
    return run_unstructured_workflow_job_for_file(
        client,
        request_parameters=request_parameters,
        src=src,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        api_key=api_key,
        api_url=api_url,
    )
