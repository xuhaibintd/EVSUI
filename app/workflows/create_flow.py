from __future__ import annotations

import asyncio
import json
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
    normalize_document_files_for_create,
    strip_create_ingestor_params,
    strip_file_based_create_params,
)
from app.utils.table_state import format_preview, row_value_by_header, table_from_result


CREATE_READY_TIMEOUT_SECONDS = 120
CREATE_READY_POLL_INTERVAL_SECONDS = 2
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
        return "unknown", "", "", f"Status check failed: {ex}"

    state, status_text, preview = _classify_vectorstore_status(status_output)
    return state, status_text, preview, ""


def _quote_teradata_identifier(value: str) -> str:
    identifier = str(value or "").strip()
    if not _TERADATA_IDENTIFIER_RE.match(identifier):
        raise ValueError(f"unsafe Teradata identifier: {identifier!r}")
    return f'"{identifier}"'


def _scalar_from_sql_result(result) -> int | None:
    headers, rows = table_from_result(result)
    if rows and rows[0]:
        value_index = 1 if headers and headers[0] == "#" and len(rows[0]) > 1 else 0
        try:
            return int(str(rows[0][value_index]).strip())
        except ValueError:
            return None
    if hasattr(result, "iloc"):
        try:
            return int(result.iloc[0, 0])
        except Exception:
            return None
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


async def _wait_for_vectorstore_ready(vector_store) -> tuple[bool, str, str, str]:
    attempts = max(1, int(CREATE_READY_TIMEOUT_SECONDS / CREATE_READY_POLL_INTERVAL_SECONDS))
    last_state = "unknown"
    last_status_text = ""
    last_preview = ""

    for attempt in range(attempts):
        state, status_text, preview, error = _read_vectorstore_status(vector_store)
        last_state = state
        last_status_text = status_text
        last_preview = preview
        if error:
            return False, preview, error, status_text
        if state == "ready":
            return True, preview, "", status_text
        if state == "failed":
            detail = status_text or preview or "unknown failure"
            return False, preview, f"VectorStore.status() reported failure: {detail}", status_text
        if attempt < attempts - 1:
            await asyncio.sleep(CREATE_READY_POLL_INTERVAL_SECONDS)

    current_detail = last_status_text or last_preview or last_state or "unknown"
    return (
        False,
        last_preview,
        f"VectorStore.status() did not reach Ready within {CREATE_READY_TIMEOUT_SECONDS}s. Current status: {current_detail}",
        last_status_text,
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
    loaded_csv_run_id = str(form.get("bookrag_loaded_csv_run_id") or "").strip()
    loaded_run_error = ""
    if raw_doc_pipeline_mode == "multi_format_bookrag" and loaded_csv_run_id:
        try:
            loaded_summary = get_ready_bookrag_csv_load_summary(csv_run_id=loaded_csv_run_id)
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
    uses_loaded_bookrag_tables = raw_doc_pipeline_mode == "multi_format_bookrag" and bool(loaded_csv_run_id)
    if not (has_uploaded_documents or has_document_files or uses_loaded_bookrag_tables):
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
            if current_state == "ready":
                warnings.append(
                    f"VectorStore '{vector_store_name}' already exists. Skipped preprocessing and create()."
                )
                result_status = "ok_with_warnings"
                result_message = f"Step 2 skipped preprocessing and VectorStore.create(): '{vector_store_name}' already exists."
                if existence_check_detail:
                    result_message = f"{result_message} {existence_check_detail}"
            else:
                result_status = "error"
                current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                result_message = (
                    f"Step 2 blocked before preprocessing: VectorStore '{vector_store_name}' already exists, "
                    f"but current status is not Ready ({current_detail})."
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
                "status_output_preview": precheck_status_preview,
                "multi_format_summary": None,
            }
            app.state.last_create_operation = result
            if result_status == "error":
                app.state.evs_state["last_success"] = ""
                app.state.evs_state["last_error"] = result_message
            else:
                app.state.evs_state["last_error"] = ""
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

            ready_confirmed, status_output_preview, readiness_error, _ready_status_text = await _wait_for_vectorstore_ready(
                vector_store
            )
            if (not ready_confirmed) and readiness_error and callable(verify_vectorstore_exists_fn):
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
                        warnings.append(
                            f"Primary VectorStore.status() check was inconclusive after create(); fallback probe confirmed '{vector_store_name}' is Ready."
                        )
                    elif fallback_status_error and not readiness_error:
                        readiness_error = fallback_status_error
                    elif fallback_error and not readiness_error:
                        readiness_error = fallback_error

            if mode_summary and mode_summary.get("source") == "loaded_csv_tables":
                target_database_for_index = str(mode_summary.get("target_database") or "").strip()
                index_row_count, index_count_error = _bookrag_vector_index_row_count(
                    vector_store_name=vector_store_name,
                    target_database=target_database_for_index,
                    execute_sql_fn=execute_sql_fn,
                )
                if index_row_count is not None:
                    index_message = (
                        f"BookRAG vector index rows: "
                        f"{target_database_for_index}.vectorstore_{vector_store_name}_index={index_row_count}."
                    )
                    if status_output_preview:
                        status_output_preview = f"{status_output_preview}\n{index_message}"
                    else:
                        status_output_preview = index_message
                    if index_row_count <= 0:
                        ready_confirmed = False
                        readiness_error = (
                            f"BookRAG vector index table is empty: "
                            f"{target_database_for_index}.vectorstore_{vector_store_name}_index has 0 rows."
                        )
                    elif not ready_confirmed and readiness_error.startswith("Status check failed:"):
                        ready_confirmed = True
                        warnings.append(
                            "VectorStore.status() failed after create(), but BookRAG index row-count check confirmed rows were created."
                        )
                elif index_count_error:
                    ready_confirmed = False
                    readiness_error = f"BookRAG vector index row-count check failed: {index_count_error}"

            if ready_confirmed:
                _mark_mode_status("ready")
                vector_create_elapsed = time.perf_counter() - vector_create_started
                result_status = "ok_with_warnings" if warnings else "ok"
                result_message = "Step 2 completed. VectorStore.create() executed successfully and status is Ready."
                append_message_fn = getattr(doc_pipeline_handler, "append_success_message", None)
                if callable(append_message_fn):
                    result_message = append_message_fn(result_message, mode_summary)
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
            else:
                vector_create_elapsed = time.perf_counter() - vector_create_started
                result_status = "error"
                result_message = (
                    "Step 2 did not finish: VectorStore.create() returned, but "
                    f"{readiness_error}"
                )
                result_message = _append_elapsed(result_message, elapsed_seconds=vector_create_elapsed)
                _mark_mode_status("failed", error=result_message)
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
                else:
                    result_status = "error"
                    current_detail = current_status_error or current_status_text or current_status_preview or "unknown"
                    result_message = (
                        f"Step 2 blocked: VectorStore '{vector_store_name}' already exists, but current status is not Ready "
                        f"({current_detail})."
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
        app.state.evs_state["last_error"] = result_message
    else:
        app.state.evs_state["last_error"] = ""
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
