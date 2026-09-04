from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.security import (
    redact_sensitive_data,
    redact_sensitive_text,
    sensitive_values,
)
from app.integrations.teradata import activated_connection
from app.runtime import PROJECT_DIR, VS_BASICS_DIR
from app.services.doc_modes.registry import get_doc_pipeline_handler
from app.services.multi_format import (
    run_bookrag_csv_load,
    run_bookrag_document_parsing,
    run_bookrag_json_to_csv,
    run_multi_format_csv_load,
    run_multi_format_document_parsing,
    run_multi_format_json_to_csv,
    strip_create_ingestor_params,
    strip_file_based_create_params,
)
from app.teradata_runtime import VectorStore
from app.utils.uploads import resolve_path_hint
from app.utils.table_state import format_preview
from app.workflows.create_status import read_vectorstore_status


BOOKRAG_PARSE_JOB = "bookrag.documents.parse"
BOOKRAG_CSV_GENERATE_JOB = "bookrag.csv.generate"
BOOKRAG_CSV_LOAD_JOB = "bookrag.csv.load"
MULTI_FORMAT_PARSE_JOB = "multi_format.documents.parse"
MULTI_FORMAT_CSV_GENERATE_JOB = "multi_format.csv.generate"
MULTI_FORMAT_CSV_LOAD_JOB = "multi_format.csv.load"
VECTOR_STORE_CREATE_JOB = "vector_store.create"

WORKFLOW_JOB_LABELS = {
    BOOKRAG_PARSE_JOB: "BookRAG document parsing",
    BOOKRAG_CSV_GENERATE_JOB: "BookRAG CSV generation",
    BOOKRAG_CSV_LOAD_JOB: "BookRAG table loading",
    MULTI_FORMAT_PARSE_JOB: "Multi-Format document parsing",
    MULTI_FORMAT_CSV_GENERATE_JOB: "Multi-Format CSV generation",
    MULTI_FORMAT_CSV_LOAD_JOB: "Multi-Format table loading",
    VECTOR_STORE_CREATE_JOB: "Vector Store creation",
}


def _job_profile_id(payload: dict[str, Any]) -> int | None:
    value = (payload.get("_job") or {}).get("connection_profile_id")
    return int(value) if value is not None else None


def _unstructured_params(auth_store) -> dict[str, str]:
    config = auth_store.get_unstructured_config()
    return {
        "unstructured_api_url": str(config.get("api_url") or "").strip(),
        "unstructured_api_key": str(config.get("api_key") or "").strip(),
    }


@contextmanager
def _redacted_runtime_errors(*secret_sources: dict[str, Any]):
    secrets = [secret for source in secret_sources for secret in sensitive_values(source)]
    try:
        yield
    except Exception as ex:
        raise RuntimeError(redact_sensitive_text(ex, secrets=secrets)) from None


def _resolve_worker_path(path_hint: str) -> str:
    return resolve_path_hint(path_hint, PROJECT_DIR, VS_BASICS_DIR)


def _register_summary_artifacts(
    lifecycle,
    summary: dict[str, Any] | None,
    payload: dict[str, Any],
    *,
    retention_days: int,
) -> int:
    if lifecycle is None or not summary:
        return 0
    job_context = payload.get("_job") or {}
    stage_roots: list[Path] = [PROJECT_DIR]
    for key in ("raw_stage_dir", "csv_stage_dir"):
        value = str(summary.get(key) or "").strip()
        if value:
            stage_roots.append(Path(value))

    candidates: set[Path] = set()

    def collect(value: Any, key: str = "") -> None:
        normalized_key = key.lower()
        if isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif isinstance(value, str) and (
            normalized_key.endswith("_path")
            or "json_file" in normalized_key
            or "csv_file" in normalized_key
        ):
            hint = Path(value)
            attempts = [hint] if hint.is_absolute() else [root / hint for root in stage_roots]
            for attempt in attempts:
                try:
                    resolved = attempt.expanduser().resolve()
                except OSError:
                    continue
                if resolved.is_file():
                    candidates.add(resolved)
                    break

    collect(summary)
    registered = 0
    for candidate in sorted(candidates, key=str):
        try:
            lifecycle.register_file(
                candidate,
                kind="workflow-output",
                retention_days=retention_days,
                job_id=str(job_context.get("id") or "") or None,
                owner_user_id=job_context.get("owner_user_id"),
            )
        except (FileNotFoundError, ValueError):
            continue
        registered += 1
    return registered


def _create_result(
    payload: dict[str, Any],
    *,
    status: str,
    message: str,
    warnings: list[str],
    execution_output_preview: str = "",
    status_output_preview: str = "",
    mode_summary: dict[str, Any] | None = None,
    secrets: tuple[object, ...] | list[object] = (),
) -> dict[str, Any]:
    return redact_sensitive_data(
        {
            "status": status,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "message": message,
            "vector_store_name": str(payload.get("vector_store_name") or ""),
            "create_preset": str(payload.get("create_preset") or "auto"),
            "create_mode": str(payload.get("create_mode") or "core"),
            "uploaded_files": list(payload.get("uploaded_files") or []),
            "warnings": warnings,
            "create_payload_json": json.dumps(
                redact_sensitive_data(payload.get("create_payload") or {}),
                indent=2,
                ensure_ascii=False,
            ),
            "create_execute_payload_json": json.dumps(
                redact_sensitive_data(payload.get("exec_payload") or {}),
                indent=2,
                ensure_ascii=False,
            ),
            "create_call_preview": str(payload.get("create_call_preview") or ""),
            "execution_output_preview": execution_output_preview,
            "status_output_preview": status_output_preview,
            "multi_format_summary": mode_summary,
        },
        secrets=secrets,
    )


def _wait_for_ready(
    vector_store,
    heartbeat: Callable[[int], None],
    *,
    interval: float,
    timeout: float,
) -> tuple[str, str, str]:
    interval = max(0.1, float(interval))
    timeout = max(60.0, float(timeout))
    deadline = time.monotonic() + timeout
    last_preview = ""
    last_detail = ""
    while True:
        state, status_text, preview, error = read_vectorstore_status(vector_store)
        last_preview = preview or last_preview
        last_detail = error or status_text or last_detail
        if state == "ready":
            return "ready", last_preview, ""
        if state == "failed":
            return "failed", last_preview, status_text or error or "VectorStore status reported failure."
        if time.monotonic() >= deadline:
            return "pending", last_preview, last_detail or f"status did not reach Ready within {timeout:.0f}s"
        elapsed_ratio = 1.0 - max(0.0, deadline - time.monotonic()) / timeout
        heartbeat(65 + min(29, int(elapsed_ratio * 30)))
        time.sleep(interval)


def build_workflow_job_handlers(
    auth_store,
    *,
    artifact_lifecycle=None,
    artifact_retention_days: int = 30,
    vectorstore_ready_timeout_seconds: float = 7200.0,
    vectorstore_ready_poll_seconds: float = 5.0,
) -> dict[str, Callable[[dict[str, Any], Callable[[int], None]], dict[str, Any]]]:
    def bookrag_parse(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(10)
        unstructured = _unstructured_params(auth_store)
        with _redacted_runtime_errors(unstructured):
            summary = run_bookrag_document_parsing(
                create_values=dict(payload.get("create_values") or {}),
                vector_store_name=str(payload.get("vector_store_name") or ""),
                uploaded_documents=list(payload.get("uploaded_documents") or []),
                connection_params=unstructured,
                resolve_path_hint=_resolve_worker_path,
            )
        heartbeat(95)
        safe_summary = redact_sensitive_data(summary, secrets=sensitive_values(unstructured))
        return {
            "summary": safe_summary,
            "artifact_count": _register_summary_artifacts(
                artifact_lifecycle, safe_summary, payload, retention_days=artifact_retention_days
            ),
        }

    def bookrag_generate(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(10)
        summary = run_bookrag_json_to_csv(
            parse_run_id=str(payload.get("parse_run_id") or ""),
            create_values=dict(payload.get("create_values") or {}),
            vector_store_name=str(payload.get("vector_store_name") or ""),
            target_database=str(payload.get("target_database") or ""),
        )
        heartbeat(95)
        return {
            "summary": summary,
            "artifact_count": _register_summary_artifacts(
                artifact_lifecycle, summary, payload, retention_days=artifact_retention_days
            ),
        }

    def bookrag_load(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(5)
        with activated_connection(auth_store, _job_profile_id(payload)) as runtime:
            heartbeat(15)
            summary = run_bookrag_csv_load(
                csv_run_id=str(payload.get("csv_run_id") or ""),
                execute_sql_fn=runtime["execute_sql"],
            )
        heartbeat(95)
        return {"summary": summary}

    def multi_format_parse(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(10)
        unstructured = _unstructured_params(auth_store)
        with _redacted_runtime_errors(unstructured):
            summary = run_multi_format_document_parsing(
                create_values=dict(payload.get("create_values") or {}),
                vector_store_name=str(payload.get("vector_store_name") or ""),
                uploaded_documents=list(payload.get("uploaded_documents") or []),
                connection_params=unstructured,
                resolve_path_hint=_resolve_worker_path,
            )
        heartbeat(95)
        safe_summary = redact_sensitive_data(summary, secrets=sensitive_values(unstructured))
        return {
            "summary": safe_summary,
            "artifact_count": _register_summary_artifacts(
                artifact_lifecycle, safe_summary, payload, retention_days=artifact_retention_days
            ),
        }

    def multi_format_generate(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(10)
        summary = run_multi_format_json_to_csv(
            parse_run_id=str(payload.get("parse_run_id") or ""),
            vector_store_name=str(payload.get("vector_store_name") or ""),
            target_database=str(payload.get("target_database") or ""),
        )
        heartbeat(95)
        return {
            "summary": summary,
            "artifact_count": _register_summary_artifacts(
                artifact_lifecycle, summary, payload, retention_days=artifact_retention_days
            ),
        }

    def multi_format_load(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        heartbeat(5)
        with activated_connection(auth_store, _job_profile_id(payload)) as runtime:
            heartbeat(15)
            summary = run_multi_format_csv_load(
                csv_run_id=str(payload.get("csv_run_id") or ""),
                execute_sql_fn=runtime["execute_sql"],
            )
        heartbeat(95)
        return {"summary": summary}

    def vector_store_create(payload: dict[str, Any], heartbeat: Callable[[int], None]) -> dict[str, Any]:
        warnings = [str(item) for item in list(payload.get("warnings") or [])]
        vector_store_name = str(payload.get("vector_store_name") or "").strip()
        create_values = dict(payload.get("create_values") or {})
        exec_payload = dict(payload.get("exec_payload") or {})
        handler = get_doc_pipeline_handler(str(payload.get("doc_pipeline_mode") or ""))
        mark_status = getattr(handler, "mark_vectorstore_status", None)
        unstructured = _unstructured_params(auth_store)
        external_secrets = sensitive_values(unstructured)

        with _redacted_runtime_errors(unstructured), activated_connection(
            auth_store, _job_profile_id(payload)
        ) as runtime:
            heartbeat(10)
            processed_payload, mode_summary = handler.preprocess_create_payload(
                exec_payload=exec_payload,
                create_values=create_values,
                vector_store_name=vector_store_name,
                connection_params=unstructured,
                execute_sql_fn=runtime["execute_sql"],
                resolve_path_hint=_resolve_worker_path,
            )
            if mode_summary:
                warnings.extend(str(item) for item in list(mode_summary.get("warnings") or []))
            artifact_count = _register_summary_artifacts(
                artifact_lifecycle,
                mode_summary,
                payload,
                retention_days=artifact_retention_days,
            )
            if bool(mode_summary and mode_summary.get("skip_vectorstore_create")):
                message_builder = getattr(handler, "build_skip_create_message", None)
                message = (
                    message_builder(mode_summary)
                    if callable(message_builder)
                    else "Preprocessing completed; VectorStore.create() was intentionally skipped."
                )
                return {
                    "create_result": _create_result(
                        payload,
                        status="ok_with_warnings" if warnings else "ok",
                        message=message,
                        warnings=warnings,
                        execution_output_preview="VectorStore.create() skipped intentionally.",
                        mode_summary=mode_summary,
                        secrets=external_secrets,
                    ),
                    "artifact_count": artifact_count,
                }
            if VectorStore is None:
                raise RuntimeError("VectorStore runtime is unavailable in the worker environment.")
            if handler.MODE in {"multi_format", "multi_format_bookrag"}:
                processed_payload = strip_file_based_create_params(processed_payload)
                processed_payload["nv_ingestor"] = None
            else:
                processed_payload = strip_create_ingestor_params(processed_payload)
            if callable(mark_status):
                mark_status(mode_summary, status="creating", create_payload=processed_payload)

            heartbeat(50)
            vector_store = VectorStore(vector_store_name)
            try:
                create_output = vector_store.create(**processed_payload)
            except Exception as ex:
                if "already exist" not in str(ex).lower():
                    if callable(mark_status):
                        mark_status(mode_summary, status="failed", error=str(ex))
                    raise
                warnings.append(f"VectorStore '{vector_store_name}' already exists; its current status was reused.")
            execution_preview = format_preview(locals().get("create_output"))
            state, status_preview, readiness_error = _wait_for_ready(
                vector_store,
                heartbeat,
                interval=vectorstore_ready_poll_seconds,
                timeout=vectorstore_ready_timeout_seconds,
            )
            if state == "ready":
                if callable(mark_status):
                    mark_status(mode_summary, status="ready")
                message = "VectorStore creation completed and status is Ready."
                append_message = getattr(handler, "append_success_message", None)
                if callable(append_message):
                    message = append_message(message, mode_summary)
                result_status = "ok_with_warnings" if warnings else "ok"
            elif state == "failed":
                message = f"VectorStore creation failed: {readiness_error}"
                if callable(mark_status):
                    mark_status(mode_summary, status="failed", error=message)
                raise RuntimeError(message)
            else:
                message = f"VectorStore creation did not reach Ready before timeout: {readiness_error}"
                if callable(mark_status):
                    mark_status(mode_summary, status="failed", error=message)
                raise RuntimeError(message)
            heartbeat(95)
            return {
                "create_result": _create_result(
                    payload,
                    status=result_status,
                    message=message,
                    warnings=warnings,
                    execution_output_preview=execution_preview,
                    status_output_preview=status_preview,
                    mode_summary=mode_summary,
                    secrets=external_secrets,
                ),
                "artifact_count": artifact_count,
            }

    return {
        BOOKRAG_PARSE_JOB: bookrag_parse,
        BOOKRAG_CSV_GENERATE_JOB: bookrag_generate,
        BOOKRAG_CSV_LOAD_JOB: bookrag_load,
        MULTI_FORMAT_PARSE_JOB: multi_format_parse,
        MULTI_FORMAT_CSV_GENERATE_JOB: multi_format_generate,
        MULTI_FORMAT_CSV_LOAD_JOB: multi_format_load,
        VECTOR_STORE_CREATE_JOB: vector_store_create,
    }
