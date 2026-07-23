from __future__ import annotations

import asyncio
import json
import os
import re
import time

from app.services.create_config import (
    CORE_CREATE_FIELDS,
    CREATE_FIELDS,
    CREATE_FIELD_MAX_LEN,
    NON_NEGATIVE_INT_FIELDS,
    apply_create_preset,
    build_create_call_preview,
    coerce_create_param,
    default_create_values,
)
from app.services.doc_modes.constants import collect_doc_pipeline_ui_values
from app.services.doc_modes.registry import get_doc_pipeline_handler
from app.services.multi_format import (
    get_ready_bookrag_csv_load_summary,
    get_ready_multi_format_csv_load_summary,
    normalize_document_files_for_create,
    strip_create_ingestor_params,
    strip_file_based_create_params,
)
from app.utils.table_state import format_preview, row_value_by_header, table_from_result

def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _optional_positive_float_env(name: str) -> float | None:
    raw_value = os.getenv(name)
    if raw_value is None or not str(raw_value).strip():
        return None
    try:
        value = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


CREATE_READY_TIMEOUT_SECONDS = _optional_positive_float_env("EVS_VECTORSTORE_READY_TIMEOUT_SECONDS")
CREATE_READY_POLL_INTERVAL_SECONDS = _positive_float_env("EVS_VECTORSTORE_READY_POLL_SECONDS", 5)
BOOKRAG_INDEX_READY_TIMEOUT_SECONDS = _positive_float_env("EVS_BOOKRAG_INDEX_READY_TIMEOUT_SECONDS", 0)
_TERADATA_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _split_document_file_hints(raw_value: str) -> list[str]:
    return [chunk.strip() for chunk in str(raw_value or '').replace('\n', ',').split(',') if chunk.strip()]


def _format_elapsed(seconds: float) -> str:
    elapsed = max(0.0, float(seconds or 0.0))
    minutes = elapsed / 60.0
    return f"{minutes:.2f} min"


def _append_elapsed(message: str, *, elapsed_seconds: float | None) -> str:
    if elapsed_seconds is None:
        return message
    return f"{message} Elapsed: {_format_elapsed(elapsed_seconds)}."


def _classify_vectorstore_status(status_output) -> tuple[str, str, str]:
    preview = format_preview(status_output, max_chars=None)
    headers, rows = table_from_result(status_output)

    status_text = ""
    for row in rows:
        status_text = row_value_by_header(headers, row, ("status", "state", "lifecycle", "operationstatus", "collectionstatus"))
        if status_text:
            break

    normalized = status_text.strip().lower()
    retry_after_text = ""
    for row in rows:
        retry_after_text = row_value_by_header(headers, row, ("retryafter",))
        if retry_after_text:
            break
    if (not normalized) and isinstance(status_output, str):
        status_text = status_output.strip()
        normalized = status_text.lower()

    if retry_after_text and not normalized:
        return "in_progress", retry_after_text, preview
    if retry_after_text:
        return "in_progress", status_text or retry_after_text, preview
    if not normalized:
        return "unknown", status_text, preview
    if "ready" in normalized:
        return "ready", status_text, preview
    if "failed" in normalized or "error" in normalized:
        return "failed", status_text, preview

    in_progress_markers = (
        "initialized",
        "ingested",
        "ingested_partially",
        "create_load_data_completed",
        "create_generating_embeddings_completed",
        "generate_embeddings_completed",
        "create_index_completed",
        "creating",
        "initializing",
        "pending",
        "processing",
        "ingesting",
        "loading",
        "generating",
        "indexing",
        "submitted",
        "updating",
        "create_",
        "update_",
        "create ",
        "update ",
    )
    if any(marker in normalized for marker in in_progress_markers):
        return "in_progress", status_text, preview
    return "unknown", status_text, preview


def _read_vectorstore_status(vector_store) -> tuple[str, str, str, str]:
    status_fn = getattr(vector_store, "status", None)
    if not callable(status_fn):
        return "unknown", "", "", "VectorStore.status() is not callable."
    try:
        status_output = status_fn()
    except Exception as ex:
        error_text = str(ex)
        normalized_error = error_text.lower()
        if "failed" in normalized_error and any(
            marker in normalized_error
            for marker in ("create", "update", "initialize", "vector store", "vectorstore")
        ):
            return "failed", error_text, "", ""
        return "unknown", "", "", f"Status check failed: {ex}"

    state, status_text, preview = _classify_vectorstore_status(status_output)
    return state, status_text, preview, ""


def _quote_teradata_identifier(value: str) -> str:
    identifier = str(value or "").strip()
    if not _TERADATA_IDENTIFIER_RE.match(identifier):
        raise ValueError(f"unsafe Teradata identifier: {identifier!r}")
    return f'"{identifier}"'


def _first_scalar(value):
    if isinstance(value, dict):
        return next(iter(value.values()), None)
    if isinstance(value, (str, bytes, bytearray)):
        return value
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    try:
        return value[0]
    except Exception:
        return value


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _scalar_from_sql_result(result) -> int | None:
    """Read an integer scalar from DB-API cursors and test-friendly table results."""
    if result is None:
        return None

    fetchone = getattr(result, "fetchone", None)
    fetchall = getattr(result, "fetchall", None)
    if callable(fetchone) or callable(fetchall):
        parsed = None
        try:
            if callable(fetchone):
                row = fetchone()
                parsed = _int_or_none(_first_scalar(row)) if row is not None else None
            if parsed is None and callable(fetchall):
                remaining_rows = fetchall() or []
                if remaining_rows:
                    parsed = _int_or_none(_first_scalar(remaining_rows[0]))
        except Exception:
            parsed = None
        finally:
            close = getattr(result, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        return parsed

    if hasattr(result, "iloc"):
        try:
            parsed = _int_or_none(result.iloc[0, 0])
            if parsed is not None:
                return parsed
        except Exception:
            pass

    if isinstance(result, dict):
        parsed = _int_or_none(_first_scalar(result))
        if parsed is not None:
            return parsed
    if isinstance(result, (list, tuple)) and result:
        parsed = _int_or_none(_first_scalar(result[0]))
        if parsed is not None:
            return parsed

    headers, rows = table_from_result(result)
    if rows and rows[0]:
        value_index = 1 if headers and headers[0] == "#" and len(rows[0]) > 1 else 0
        return _int_or_none(rows[0][value_index])
    return None


def _bookrag_vector_index_row_count(
    *,
    vector_store_name: str,
    target_database: str,
    execute_sql_fn,
) -> tuple[int | None, str]:
    if execute_sql_fn is None:
        return None, "execute_sql is unavailable"
    try:
        schema_sql = _quote_teradata_identifier(target_database)
        table_sql = _quote_teradata_identifier(f"vectorstore_{vector_store_name}_index")
    except ValueError as ex:
        return None, str(ex)
    sql = f"SELECT COUNT(*) FROM {schema_sql}.{table_sql}"
    try:
        count_result = execute_sql_fn(sql)
    except Exception as ex:
        return None, str(ex)
    count = _scalar_from_sql_result(count_result)
    if count is None:
        return None, f"could not parse row count from {format_preview(count_result, max_chars=300)}"
    return count, ""


def _bookrag_source_embedding_row_count(
    *,
    source_table_name: str,
    target_database: str,
    execute_sql_fn,
) -> tuple[int | None, str]:
    return _source_embedding_row_count(
        source_table_name=source_table_name,
        target_database=target_database,
        data_column="content",
        execute_sql_fn=execute_sql_fn,
    )


def _multi_format_source_embedding_row_count(
    *,
    source_table_name: str,
    target_database: str,
    execute_sql_fn,
) -> tuple[int | None, str]:
    return _source_embedding_row_count(
        source_table_name=source_table_name,
        target_database=target_database,
        data_column="text",
        execute_sql_fn=execute_sql_fn,
    )


def _source_embedding_row_count(
    *,
    source_table_name: str,
    target_database: str,
    data_column: str,
    execute_sql_fn,
) -> tuple[int | None, str]:
    if execute_sql_fn is None:
        return None, "execute_sql is unavailable"
    try:
        schema_sql = _quote_teradata_identifier(target_database)
        table_sql = _quote_teradata_identifier(source_table_name)
        data_column_sql = _quote_teradata_identifier(data_column)
    except ValueError as ex:
        return None, str(ex)
    sql = (
        f'SELECT COUNT(*) FROM {schema_sql}.{table_sql} '
        f"WHERE {data_column_sql} IS NOT NULL AND TRIM({data_column_sql}) <> ''"
    )
    try:
        count_result = execute_sql_fn(sql)
    except Exception as ex:
        return None, str(ex)
    count = _scalar_from_sql_result(count_result)
    if count is None:
        return None, f"could not parse source row count from {format_preview(count_result, max_chars=300)}"
    return count, ""


async def _wait_for_bookrag_index_rows(
    *,
    vector_store_name: str,
    target_database: str,
    expected_row_count: int | None,
    execute_sql_fn,
) -> tuple[int | None, str]:
    deadline = time.monotonic() + max(0.0, float(BOOKRAG_INDEX_READY_TIMEOUT_SECONDS))
    last_count: int | None = None
    last_error = ""
    first_attempt = True
    while first_attempt or time.monotonic() < deadline:
        first_attempt = False
        last_count, last_error = _bookrag_vector_index_row_count(
            vector_store_name=vector_store_name,
            target_database=target_database,
            execute_sql_fn=execute_sql_fn,
        )
        minimum_rows = expected_row_count if expected_row_count is not None else 1
        if last_count is not None and last_count >= minimum_rows:
            return last_count, ""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(float(CREATE_READY_POLL_INTERVAL_SECONDS), remaining))

    if last_count is not None:
        expected_detail = (
            f"; expected {expected_row_count} non-empty source rows"
            if expected_row_count is not None
            else ""
        )
        return last_count, f"index row count remained {last_count}{expected_detail}"
    return None, last_error or "index row count remained unavailable"


async def _wait_for_vectorstore_ready(vector_store) -> tuple[bool, str, str, str, str]:
    deadline = (
        time.monotonic() + max(0.0, float(CREATE_READY_TIMEOUT_SECONDS))
        if CREATE_READY_TIMEOUT_SECONDS is not None
        else None
    )
    last_state = "unknown"
    last_status_text = ""
    last_preview = ""
    first_attempt = True

    while first_attempt or deadline is None or time.monotonic() < deadline:
        first_attempt = False
        state, status_text, preview, error = _read_vectorstore_status(vector_store)
        last_state = state
        last_status_text = status_text
        last_preview = preview
        if error:
            return False, preview, error, status_text, "check_error"
        if state == "ready":
            return True, preview, "", status_text, "ready"
        if state == "failed":
            detail = status_text or preview or "unknown failure"
            return False, preview, f"VectorStore.status() reported failure: {detail}", status_text, "failed"
        if deadline is None:
            await asyncio.sleep(float(CREATE_READY_POLL_INTERVAL_SECONDS))
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(float(CREATE_READY_POLL_INTERVAL_SECONDS), remaining))

    current_detail = last_status_text or last_preview or last_state or "unknown"
    return (
        False,
        last_preview,
        f"VectorStore.status() did not reach Ready within {CREATE_READY_TIMEOUT_SECONDS}s. Current status: {current_detail}",
        last_status_text,
        "pending",
    )


async def handle_upload_and_prepare_create(
    request,
    app,
    templates,
    *,
    vector_store_cls,
    execute_sql_fn,
    save_document_uploads_fn,
    collect_upload_files_fn,
    resolve_path_hint_fn,
    now_ts,
    is_htmx: bool,
    is_vectorstore_already_exists_error_fn,
    verify_vectorstore_exists_fn,
    append_connect_step,
):
    if not app.state.evs_state["connected"]:
        app.state.evs_state["last_success"] = ""
        app.state.evs_state["last_error"] = "Connect/authenticate in Step 1 first."
        return templates.TemplateResponse(
            request,
            "partials/create_result.html",
            {
                "create_result": {
                    "status": "error",
                    "time": now_ts(),
                    "message": "Connect/authenticate in Step 1 first.",
                },
                "evs": app.state.evs_state,
                "is_htmx": is_htmx,
            },
        )

    form = await request.form()
    files = collect_upload_files_fn(form, field_name="files")

    saved: list[dict] = []
    upload_notices: list[str] = []
    if files:
        saved, upload_notices = await save_document_uploads_fn(files)
    if saved:
        app.state.document_uploads = saved
    app.state.document_upload_notices = upload_notices

    create_values: dict[str, str] = default_create_values()
    vector_store_name = str(form.get("vector_store_name", "")).strip()
    requested_preset = str(form.get("create_preset", "auto")).strip().lower() or "auto"
    create_mode = str(form.get("create_mode", "core")).strip().lower() or "core"
    selected_search_algorithm = str(form.get("search_algorithm", "")).strip().upper()
    if requested_preset in {"vectordistance", "hnsw", "kmeans"}:
        create_preset = requested_preset
    elif selected_search_algorithm in {"VECTORDISTANCE", "HNSW", "KMEANS"}:
        create_preset = selected_search_algorithm.lower()
    else:
        create_preset = "auto"

    raw_doc_pipeline_mode = str(form.get("doc_pipeline_mode", "")).strip()
    doc_pipeline_mode = raw_doc_pipeline_mode
    bookrag_loaded_csv_run_id = str(form.get("bookrag_loaded_csv_run_id") or "").strip()
    multi_format_loaded_csv_run_id = str(form.get("multi_format_loaded_csv_run_id") or "").strip()
    loaded_csv_run_id = ""
    loaded_summary: dict | None = None
    loaded_run_error = ""
    if raw_doc_pipeline_mode == "multi_format_bookrag" and bookrag_loaded_csv_run_id:
        loaded_csv_run_id = bookrag_loaded_csv_run_id
        try:
            loaded_summary = get_ready_bookrag_csv_load_summary(csv_run_id=loaded_csv_run_id)
            vector_store_name = str(loaded_summary.get("vector_store_name") or "").strip()
        except Exception as ex:
            loaded_run_error = str(ex)
    elif raw_doc_pipeline_mode == "multi_format" and multi_format_loaded_csv_run_id:
        loaded_csv_run_id = multi_format_loaded_csv_run_id
        try:
            loaded_summary = get_ready_multi_format_csv_load_summary(csv_run_id=loaded_csv_run_id)
            vector_store_name = str(loaded_summary.get("vector_store_name") or "").strip()
        except Exception as ex:
            loaded_run_error = str(ex)
    create_values["vector_store_name"] = vector_store_name
    create_values["create_preset"] = create_preset
    create_values["create_mode"] = create_mode
    create_values["doc_pipeline_mode"] = doc_pipeline_mode
    create_values.update(collect_doc_pipeline_ui_values(form, field_max_len=CREATE_FIELD_MAX_LEN))

    if loaded_run_error:
        app.state.create_form_values = create_values
        return templates.TemplateResponse(
            request,
            "partials/create_result.html",
            {
                "create_result": {
                    "status": "error",
                    "time": now_ts(),
                    "message": f"Selected loaded-table run is unavailable: {loaded_run_error}",
                },
                "evs": app.state.evs_state,
                "is_htmx": is_htmx,
            },
        )

    required_missing: list[str] = []
    if not vector_store_name:
        required_missing.append("vector_store_name")
    if not raw_doc_pipeline_mode:
        required_missing.append("doc_pipeline_mode")
    embeddings_model_value = str(form.get("embeddings_model", "")).strip()
    if not embeddings_model_value:
        required_missing.append("embeddings_model")
    has_document_files = bool(_split_document_file_hints(form.get("document_files", "")))
    has_uploaded_documents = bool(saved or app.state.document_uploads)
    uses_loaded_tables = raw_doc_pipeline_mode in {"multi_format", "multi_format_bookrag"} and bool(loaded_csv_run_id)
    if not (has_uploaded_documents or has_document_files or uses_loaded_tables):
        required_missing.append("document_source")

    if required_missing:
        app.state.create_form_values = create_values
        return templates.TemplateResponse(
            request,
            "partials/create_result.html",
            {
                "create_result": {
                    "status": "error",
                    "time": now_ts(),
                    "message": f"Required fields missing: {', '.join(required_missing)}",
                },
                "evs": app.state.evs_state,
                "is_htmx": is_htmx,
            },
        )

    doc_pipeline_handler = get_doc_pipeline_handler(raw_doc_pipeline_mode)
    doc_pipeline_mode = doc_pipeline_handler.MODE
    create_values["doc_pipeline_mode"] = doc_pipeline_mode
    should_run_vectorstore_create_fn = getattr(doc_pipeline_handler, "should_run_vectorstore_create", None)
    should_run_vectorstore_create = (
        bool(should_run_vectorstore_create_fn(create_values))
        if callable(should_run_vectorstore_create_fn)
        else (not bool(getattr(doc_pipeline_handler, "SKIP_VECTORSTORE_CREATE", False)))
    )

    def _mark_prechecked_loaded_run(status: str, *, error: str = "") -> None:
        if not loaded_summary or not loaded_csv_run_id:
            return
        mark_status_fn = getattr(doc_pipeline_handler, "mark_vectorstore_status", None)
        if callable(mark_status_fn):
            loaded_source = (
                "loaded_multi_format_csv_table"
                if raw_doc_pipeline_mode == "multi_format"
                else "loaded_csv_tables"
            )
            mark_status_fn(
                {**loaded_summary, "source": loaded_source, "csv_run_id": loaded_csv_run_id},
                status=status,
                error=error,
            )

    create_payload: dict = {}
    warnings: list[str] = list(upload_notices)
    allowed_fields = CORE_CREATE_FIELDS if create_mode == "core" else {field["name"] for field in CREATE_FIELDS}
    for field in CREATE_FIELDS:
        field_name = field["name"]
        posted = field_name in form
        raw = str(form.get(field_name, "")).strip() if posted else create_values.get(field_name, "")
        if posted and len(raw) > CREATE_FIELD_MAX_LEN:
            raw = raw[:CREATE_FIELD_MAX_LEN]
            warnings.append(f"Field [{field_name}] exceeded {CREATE_FIELD_MAX_LEN} chars and was truncated.")
        create_values[field_name] = raw
        if (not posted) or field_name not in allowed_fields or not raw:
            continue
        try:
            create_payload[field_name] = coerce_create_param(field_name, raw)
        except ValueError as ex:
            if field_name in NON_NEGATIVE_INT_FIELDS:
                warnings.append(str(ex))
                continue
            warnings.append(f"Field [{field_name}] cannot be cast; kept as string.")
            create_payload[field_name] = raw

    if saved and "document_files" not in create_payload:
        create_payload["document_files"] = [item["saved_path"] for item in saved]
    elif (not saved) and ("document_files" not in create_payload) and app.state.document_uploads:
        create_payload["document_files"] = [item["saved_path"] for item in app.state.document_uploads]

    upload_manifest = saved if saved else app.state.document_uploads
    if upload_manifest:
        create_payload["document_manifest"] = [
            {
                "doc_id": str(item.get("doc_id") or "").strip(),
                "filename": str(item.get("filename") or item.get("name") or "").strip(),
                "saved_path": str(item.get("saved_path") or "").strip(),
            }
            for item in upload_manifest
            if str(item.get("saved_path") or "").strip()
        ]

    apply_create_preset(create_payload, create_preset, vector_store_name)
    create_values["object_names"] = (
        ",".join(create_payload["object_names"])
        if isinstance(create_payload.get("object_names"), list)
        else str(create_payload.get("object_names", ""))
    )
    create_values["data_columns"] = ",".join(create_payload.get("data_columns", []))
    create_values["vector_column"] = str(create_payload.get("vector_column", ""))
    create_values["chunk_size"] = str(create_payload.get("chunk_size", ""))
    optimized_chunking = create_payload.get("optimized_chunking", "")
    create_values["optimized_chunking"] = (
        str(optimized_chunking).lower() if isinstance(optimized_chunking, bool) else str(optimized_chunking)
    )
    create_values["embeddings_model"] = str(create_payload.get("embeddings_model", ""))
    create_values["top_k"] = str(create_payload.get("top_k", ""))
    app.state.create_form_values = create_values

    exec_payload, path_warnings = normalize_document_files_for_create(
        create_payload,
        resolve_path_hint=resolve_path_hint_fn,
    )
    warnings.extend(path_warnings)

    precheck_status_preview = ""
    if should_run_vectorstore_create and callable(verify_vectorstore_exists_fn):
        verified_existing_store = False
        existence_check_detail = ""
        existence_check_error = ""
        try:
            verified_existing_store, existence_check_detail, existence_check_error = verify_vectorstore_exists_fn(
                vector_store_name,
                allow_status_fallback=False,
            )
        except Exception as ex:
            existence_check_error = str(ex)

        if verified_existing_store:
            if vector_store_cls is None:
                result_status = "error"
                result_message = (
                    f"Step 2 blocked before preprocessing: VectorStore '{vector_store_name}' already exists, "
                    "but VectorStore runtime is unavailable to verify its status."
                )
                if existence_check_detail:
                    result_message = f"{result_message} {existence_check_detail}"
                result = {
                    "status": result_status,
                    "time": now_ts(),
                    "message": result_message,
                    "vector_store_name": vector_store_name,
                    "create_preset": create_preset,
                    "create_mode": create_mode,
                    "uploaded_files": saved if saved else app.state.document_uploads,
                    "warnings": warnings,
                    "create_payload_json": json.dumps(create_payload, indent=2, ensure_ascii=False),
                    "create_execute_payload_json": json.dumps(exec_payload, indent=2, ensure_ascii=False),
                    "create_call_preview": build_create_call_preview(vector_store_name, create_payload),
                    "execution_output_preview": "",
                    "status_output_preview": existence_check_detail,
                    "multi_format_summary": None,
                }
                app.state.last_create_operation = result
                app.state.evs_state["last_success"] = ""
                app.state.evs_state["last_error"] = result_message
                return templates.TemplateResponse(
                    request,
                    "partials/create_result.html",
                    {
                        "create_result": result,
                        "evs": app.state.evs_state,
                        "is_htmx": is_htmx,
                    },
                )

            existing_vector_store = vector_store_cls(vector_store_name)
            current_state, current_status_text, current_status_preview, current_status_error = _read_vectorstore_status(
                existing_vector_store
            )
            precheck_status_preview = existence_check_detail or current_status_preview
            precheck_integrity_error = ""
            index_verification_label = "Vector"
            if (
                current_state == "ready"
                and loaded_summary
                and raw_doc_pipeline_mode in {"multi_format", "multi_format_bookrag"}
            ):
                target_database_for_index = str(loaded_summary.get("target_database") or "").strip()
                if raw_doc_pipeline_mode == "multi_format_bookrag":
                    index_verification_label = "BookRAG vector"
                    loaded_table_targets = loaded_summary.get("table_targets") or {}
                    source_table_for_index = str(
                        loaded_table_targets.get("nodes")
                        or str(loaded_summary.get("node_table") or "").rsplit(".", 1)[-1]
                    ).strip()
                    source_count_fn = _bookrag_source_embedding_row_count
                else:
                    index_verification_label = "Multi-Format vector"
                    source_table_for_index = str(loaded_summary.get("table_name") or "").strip()
                    source_count_fn = _multi_format_source_embedding_row_count
                expected_index_count, source_count_error = source_count_fn(
                    source_table_name=source_table_for_index,
                    target_database=target_database_for_index,
                    execute_sql_fn=execute_sql_fn,
                )
                strict_index_verification = raw_doc_pipeline_mode == "multi_format"
                index_row_count, index_count_error = await _wait_for_bookrag_index_rows(
                    vector_store_name=vector_store_name,
                    target_database=target_database_for_index,
                    expected_row_count=expected_index_count,
                    execute_sql_fn=execute_sql_fn,
                )
                if source_count_error:
                    if strict_index_verification:
                        precheck_integrity_error = (
                            f"source row-count verification was unavailable: {source_count_error}"
                        )
                    else:
                        warnings.append(
                            "Existing VectorStore is Ready, but source row-count verification was unavailable: "
                            f"{source_count_error}"
                        )
                if index_row_count is None:
                    if strict_index_verification:
                        precheck_integrity_error = (
                            f"index row-count verification was unavailable: {index_count_error}"
                        )
                    else:
                        warnings.append(
                            "Existing VectorStore is Ready, but index row-count verification was unavailable: "
                            f"{index_count_error}"
                        )
                else:
                    index_message = (
                        f"{index_verification_label} index rows: "
                        f"{target_database_for_index}.vectorstore_{vector_store_name}_index={index_row_count}."
                    )
                    precheck_status_preview = (
                        f"{precheck_status_preview}\n{index_message}" if precheck_status_preview else index_message
                    )
                    if strict_index_verification and index_row_count <= 0:
                        precheck_integrity_error = "index is empty"
                    elif expected_index_count is not None and index_row_count != expected_index_count:
                        precheck_integrity_error = (
                            f"index has {index_row_count} rows; expected {expected_index_count} non-empty source rows"
                        )
                    elif index_row_count <= 0:
                        precheck_integrity_error = "index is empty"

            if current_state == "ready" and not precheck_integrity_error:
                warnings.append(
                    f"VectorStore '{vector_store_name}' already exists. Skipped preprocessing and create()."
                )
                result_status = "ok_with_warnings"
                result_message = f"Step 2 skipped preprocessing and VectorStore.create(): '{vector_store_name}' already exists."
                if existence_check_detail:
                    result_message = f"{result_message} {existence_check_detail}"
                _mark_prechecked_loaded_run("ready")
            elif current_state == "ready":
                result_status = "error"
                result_message = (
                    f"Step 2 blocked before preprocessing: VectorStore '{vector_store_name}' reports Ready, "
                    f"but {index_verification_label} index verification failed ({precheck_integrity_error})."
                )
                _mark_prechecked_loaded_run("failed", error=result_message)
            elif current_state == "failed":
                result_status = "error"
                current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                result_message = (
                    f"Step 2 blocked before preprocessing: VectorStore '{vector_store_name}' already exists, "
                    f"and its current status is Failed ({current_detail})."
                )
                if existence_check_detail:
                    result_message = f"{result_message} {existence_check_detail}"
                _mark_prechecked_loaded_run("failed", error=result_message)
            else:
                result_status = "pending"
                current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                result_message = (
                    f"Step 2 is still processing: VectorStore '{vector_store_name}' already exists, "
                    f"but has not reached Ready ({current_detail}). The server-side operation was not cancelled."
                )
                if existence_check_detail:
                    result_message = f"{result_message} {existence_check_detail}"
                _mark_prechecked_loaded_run("creating")

            result = {
                "status": result_status,
                "time": now_ts(),
                "message": result_message,
                "vector_store_name": vector_store_name,
                "create_preset": create_preset,
                "create_mode": create_mode,
                "uploaded_files": saved if saved else app.state.document_uploads,
                "warnings": warnings,
                "create_payload_json": json.dumps(create_payload, indent=2, ensure_ascii=False),
                "create_execute_payload_json": json.dumps(exec_payload, indent=2, ensure_ascii=False),
                "create_call_preview": build_create_call_preview(vector_store_name, create_payload),
                "execution_output_preview": "",
                "status_output_preview": precheck_status_preview,
                "multi_format_summary": None,
            }
            app.state.last_create_operation = result
            if result_status == "error":
                app.state.evs_state["last_success"] = ""
                app.state.evs_state["last_notice"] = ""
                app.state.evs_state["last_error"] = result_message
            elif result_status == "pending":
                app.state.evs_state["last_success"] = ""
                app.state.evs_state["last_error"] = ""
                app.state.evs_state["last_notice"] = result_message
            else:
                app.state.evs_state["last_error"] = ""
                app.state.evs_state["last_notice"] = ""
                app.state.evs_state["last_success"] = result_message
                app.state.evs_state["last_created_vs_name"] = vector_store_name
                append_connect_step(
                    app.state.evs_state,
                    "VSManager.list()",
                    "info",
                    "Skipped after pre-check. Click 'Run List' manually.",
                )
            return templates.TemplateResponse(
                request,
                "partials/create_result.html",
                {
                    "create_result": result,
                    "evs": app.state.evs_state,
                    "is_htmx": is_htmx,
                },
            )

    mode_summary: dict | None = None
    mode_error = ""
    try:
        exec_payload, mode_summary = await asyncio.to_thread(
            doc_pipeline_handler.preprocess_create_payload,
            exec_payload=exec_payload,
            create_values=create_values,
            vector_store_name=vector_store_name,
            connection_params=app.state.evs_state.get("params", {}),
            execute_sql_fn=execute_sql_fn,
            resolve_path_hint=resolve_path_hint_fn,
        )
        if mode_summary:
            warnings.extend(mode_summary.get("warnings", []))
    except Exception as ex:
        mode_error = str(ex)

    execution_output_preview = ""
    status_output_preview = ""

    mode_skip_vectorstore_create = bool(mode_summary.get("skip_vectorstore_create")) if mode_summary else (not should_run_vectorstore_create)
    mark_mode_status_fn = getattr(doc_pipeline_handler, "mark_vectorstore_status", None)

    def _mark_mode_status(status: str, *, error: str = "", create_payload: dict | None = None) -> None:
        if callable(mark_mode_status_fn):
            mark_mode_status_fn(
                mode_summary,
                status=status,
                error=error,
                create_payload=create_payload,
            )

    if mode_error:
        result_status = "error"
        result_message = f"Step 2 failed during {doc_pipeline_handler.LABEL} preprocessing: {mode_error}"
    elif mode_skip_vectorstore_create:
        result_status = "ok_with_warnings" if warnings else "ok"
        result_message = doc_pipeline_handler.build_skip_create_message(mode_summary)
        execution_output_preview = f"VectorStore.create() skipped intentionally for {doc_pipeline_handler.MODE}."
    elif vector_store_cls is None:
        result_status = "error"
        result_message = "Step 2 failed: VectorStore runtime is unavailable in current environment."
        _mark_mode_status("failed", error=result_message)
    else:
        vector_create_started = time.perf_counter()
        vector_create_elapsed: float | None = None
        try:
            if doc_pipeline_handler.MODE in {"multi_format", "multi_format_bookrag"}:
                exec_payload = strip_file_based_create_params(exec_payload)
                exec_payload["nv_ingestor"] = None
            else:
                exec_payload = strip_create_ingestor_params(exec_payload)
            _mark_mode_status("creating", create_payload=exec_payload)
            vector_store = vector_store_cls(vector_store_name)
            create_output = vector_store.create(**exec_payload)
            execution_output_preview = format_preview(create_output)

            (
                ready_confirmed,
                status_output_preview,
                readiness_error,
                _ready_status_text,
                readiness_state,
            ) = await _wait_for_vectorstore_ready(vector_store)
            if (
                (not ready_confirmed)
                and readiness_state != "failed"
                and readiness_error
                and callable(verify_vectorstore_exists_fn)
            ):
                fallback_verified = False
                fallback_detail = ""
                fallback_error = ""
                try:
                    fallback_verified, fallback_detail, fallback_error = verify_vectorstore_exists_fn(
                        vector_store_name,
                        allow_status_fallback=True,
                    )
                except Exception as verify_ex:
                    fallback_error = str(verify_ex)

                if fallback_detail and not status_output_preview:
                    status_output_preview = fallback_detail

                if fallback_verified:
                    refreshed_vector_store = vector_store_cls(vector_store_name)
                    fallback_state, fallback_status_text, fallback_preview, fallback_status_error = _read_vectorstore_status(
                        refreshed_vector_store
                    )
                    if fallback_preview:
                        status_output_preview = fallback_preview
                    if fallback_state == "ready":
                        ready_confirmed = True
                        readiness_state = "ready"
                        readiness_error = ""
                        warnings.append(
                            f"Primary VectorStore.status() check was inconclusive after create(); fallback probe confirmed '{vector_store_name}' is Ready."
                        )
                    elif fallback_state == "failed":
                        readiness_state = "failed"
                        readiness_error = (
                            f"VectorStore.status() reported failure: "
                            f"{fallback_status_text or fallback_preview or 'unknown failure'}"
                        )
                    elif fallback_status_error:
                        readiness_error = fallback_status_error
                        readiness_state = "check_error"
                    elif fallback_error:
                        readiness_error = fallback_error
                        readiness_state = "check_error"

            loaded_table_source = str(mode_summary.get("source") or "") if mode_summary else ""
            if ready_confirmed and mode_summary and loaded_table_source in {
                "loaded_csv_tables",
                "loaded_multi_format_csv_table",
            }:
                target_database_for_index = str(mode_summary.get("target_database") or "").strip()
                if loaded_table_source == "loaded_csv_tables":
                    index_verification_label = "BookRAG"
                    source_data_label = "content"
                    table_targets = mode_summary.get("table_targets") or {}
                    source_table_for_index = str(
                        table_targets.get("nodes") or exec_payload.get("object_names") or ""
                    ).strip()
                    source_count_fn = _bookrag_source_embedding_row_count
                else:
                    index_verification_label = "Multi-Format"
                    source_data_label = "text"
                    source_table_for_index = str(
                        mode_summary.get("table_name") or exec_payload.get("object_names") or ""
                    ).strip()
                    source_count_fn = _multi_format_source_embedding_row_count
                expected_index_count, source_count_error = source_count_fn(
                    source_table_name=source_table_for_index,
                    target_database=target_database_for_index,
                    execute_sql_fn=execute_sql_fn,
                )
                strict_index_verification = loaded_table_source == "loaded_multi_format_csv_table"
                if source_count_error:
                    if strict_index_verification:
                        ready_confirmed = False
                        readiness_state = "failed"
                        readiness_error = (
                            f"{index_verification_label} source row-count verification was unavailable: "
                            f"{source_count_error}"
                        )
                    else:
                        warnings.append(
                            f"VectorStore is Ready, but the {index_verification_label} source row-count "
                            "verification was unavailable: "
                            f"{source_count_error}"
                        )
                elif expected_index_count is not None and expected_index_count <= 0:
                    ready_confirmed = False
                    readiness_state = "failed"
                    readiness_error = (
                        f"{index_verification_label} source table has no non-empty {source_data_label} rows: "
                        f"{target_database_for_index}.{source_table_for_index}."
                    )

                index_row_count, index_count_error = await _wait_for_bookrag_index_rows(
                    vector_store_name=vector_store_name,
                    target_database=target_database_for_index,
                    expected_row_count=expected_index_count,
                    execute_sql_fn=execute_sql_fn,
                )
                if index_row_count is not None:
                    index_message = (
                        f"{index_verification_label} vector index rows: "
                        f"{target_database_for_index}.vectorstore_{vector_store_name}_index={index_row_count}."
                    )
                    if status_output_preview:
                        status_output_preview = f"{status_output_preview}\n{index_message}"
                    else:
                        status_output_preview = index_message
                    if strict_index_verification and index_row_count <= 0:
                        ready_confirmed = False
                        readiness_state = "failed"
                        readiness_error = (
                            f"{index_verification_label} vector index table is empty after VectorStore reached Ready: "
                            f"{target_database_for_index}.vectorstore_{vector_store_name}_index has 0 rows."
                        )
                    elif expected_index_count is not None and index_row_count != expected_index_count:
                        ready_confirmed = False
                        readiness_state = "failed"
                        readiness_error = (
                            f"{index_verification_label} vector index row count is incomplete: "
                            f"{target_database_for_index}.vectorstore_{vector_store_name}_index has "
                            f"{index_row_count} rows; expected {expected_index_count} non-empty source rows."
                        )
                    elif index_row_count <= 0:
                        ready_confirmed = False
                        readiness_state = "failed"
                        readiness_error = (
                            f"{index_verification_label} vector index table is empty after VectorStore reached Ready: "
                            f"{target_database_for_index}.vectorstore_{vector_store_name}_index has 0 rows."
                        )
                elif index_count_error:
                    if strict_index_verification:
                        ready_confirmed = False
                        readiness_state = "failed"
                        readiness_error = (
                            f"{index_verification_label} vector index row-count verification was unavailable: "
                            f"{index_count_error}"
                        )
                    else:
                        warnings.append(
                            f"VectorStore is Ready, but the {index_verification_label} vector index row-count "
                            "verification was unavailable: "
                            f"{index_count_error}"
                        )

            if ready_confirmed:
                _mark_mode_status("ready")
                vector_create_elapsed = time.perf_counter() - vector_create_started
                result_status = "ok_with_warnings" if warnings else "ok"
                result_message = "Step 2 completed. VectorStore.create() executed successfully and status is Ready."
                append_message_fn = getattr(doc_pipeline_handler, "append_success_message", None)
                if callable(append_message_fn):
                    result_message = append_message_fn(result_message, mode_summary)
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
            elif readiness_state == "failed":
                vector_create_elapsed = time.perf_counter() - vector_create_started
                result_status = "error"
                result_message = (
                    "Step 2 did not finish: VectorStore.create() returned, but "
                    f"{readiness_error or 'VectorStore.status() reported failure.'}"
                )
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
                _mark_mode_status("failed", error=result_message)
            else:
                vector_create_elapsed = time.perf_counter() - vector_create_started
                result_status = "pending"
                result_message = (
                    "Step 2 is still processing: VectorStore.create() returned, but the server-side operation "
                    f"has not reached Ready yet ({readiness_error or readiness_state}). "
                    "The operation was not cancelled and may continue after this response."
                )
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
        except Exception as ex:
            vector_create_elapsed = time.perf_counter() - vector_create_started
            ex_text = str(ex)
            already_exists = is_vectorstore_already_exists_error_fn(ex_text)
            verified_existing_store = False
            existence_check_error = ""
            existence_check_detail = ""
            if already_exists and callable(verify_vectorstore_exists_fn):
                try:
                    verified_existing_store, existence_check_detail, existence_check_error = verify_vectorstore_exists_fn(
                        vector_store_name,
                        allow_status_fallback=True,
                    )
                except Exception as verify_ex:
                    existence_check_error = str(verify_ex)
            if existence_check_detail:
                status_output_preview = existence_check_detail

            if already_exists and verified_existing_store:
                existing_vector_store = locals().get("vector_store")
                if existing_vector_store is None:
                    existing_vector_store = vector_store_cls(vector_store_name)
                current_state, current_status_text, current_status_preview, current_status_error = _read_vectorstore_status(
                    existing_vector_store
                )
                if current_status_preview:
                    status_output_preview = current_status_preview
                if current_state == "ready":
                    warnings.append(
                        f"VectorStore '{vector_store_name}' already exists. Skipped create() and reused existing store."
                    )
                    result_status = "ok_with_warnings"
                    result_message = f"Step 2 skipped VectorStore.create(): '{vector_store_name}' already exists."
                    if existence_check_detail:
                        result_message = f"{result_message} {existence_check_detail}"
                    append_message_fn = getattr(doc_pipeline_handler, "append_success_message", None)
                    if callable(append_message_fn):
                        result_message = append_message_fn(result_message, mode_summary)
                    result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
                elif current_state == "failed":
                    result_status = "error"
                    current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                    result_message = (
                        f"Step 2 blocked: VectorStore '{vector_store_name}' already exists with Failed status "
                        f"({current_detail})."
                    )
                    if existence_check_detail:
                        result_message = f"{result_message} {existence_check_detail}"
                    result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
                else:
                    result_status = "pending"
                    current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                    result_message = (
                        f"Step 2 is still processing: VectorStore '{vector_store_name}' already exists and has not "
                        f"reached Ready ({current_detail}). The server-side operation was not cancelled."
                    )
                    if existence_check_detail:
                        result_message = f"{result_message} {existence_check_detail}"
                    result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
            else:
                result_status = "error"
                if already_exists:
                    if existence_check_error:
                        verification_suffix = (
                            f" (existence check failed for '{vector_store_name}': {existence_check_error})"
                        )
                    elif existence_check_detail:
                        verification_suffix = (
                            f" (existence check did not confirm '{vector_store_name}' actually exists)"
                        )
                    else:
                        verification_suffix = ""
                    result_message = f"Step 2 failed while executing VectorStore.create(): {ex}{verification_suffix}"
                else:
                    result_message = f"Step 2 failed while executing VectorStore.create(): {ex}"
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
            if result_status == "error":
                _mark_mode_status("failed", error=result_message)
            elif result_status == "pending":
                _mark_mode_status("creating")
            else:
                _mark_mode_status("ready")

    result = {
        "status": result_status,
        "time": now_ts(),
        "message": result_message,
        "vector_store_name": vector_store_name,
        "create_preset": create_preset,
        "create_mode": create_mode,
        "uploaded_files": saved if saved else app.state.document_uploads,
        "warnings": warnings,
        "create_payload_json": json.dumps(create_payload, indent=2, ensure_ascii=False),
        "create_execute_payload_json": json.dumps(exec_payload, indent=2, ensure_ascii=False),
        "create_call_preview": build_create_call_preview(vector_store_name, create_payload),
        "execution_output_preview": execution_output_preview,
        "status_output_preview": status_output_preview,
        "multi_format_summary": mode_summary,
    }
    app.state.last_create_operation = result
    if result_status == "error":
        app.state.evs_state["last_success"] = ""
        app.state.evs_state["last_notice"] = ""
        app.state.evs_state["last_error"] = result_message
    elif result_status == "pending":
        app.state.evs_state["last_success"] = ""
        app.state.evs_state["last_error"] = ""
        app.state.evs_state["last_notice"] = result_message
    else:
        app.state.evs_state["last_error"] = ""
        app.state.evs_state["last_notice"] = ""
        app.state.evs_state["last_success"] = result_message
        app.state.evs_state["last_created_vs_name"] = vector_store_name
        append_connect_step(
            app.state.evs_state,
            "VSManager.list()",
            "info",
            "Skipped after create. Click 'Run List' manually.",
        )

    return templates.TemplateResponse(
        request,
        "partials/create_result.html",
        {
            "create_result": result,
            "evs": app.state.evs_state,
            "is_htmx": is_htmx,
        },
    )
