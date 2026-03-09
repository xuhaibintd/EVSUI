from __future__ import annotations

import json

from app.services.create_config import (
    CORE_CREATE_FIELDS,
    CREATE_FIELDS,
    CREATE_FIELD_MAX_LEN,
    DOC_PIPELINE_UI_DEFAULTS,
    NON_NEGATIVE_INT_FIELDS,
    apply_create_preset,
    build_create_call_preview,
    coerce_create_param,
)
from app.services.multi_format import (
    apply_multi_format_pipeline,
    normalize_document_files_for_create,
)
from app.utils.table_state import format_preview


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

    create_values: dict[str, str] = {}
    vector_store_name = str(form.get("vector_store_name", "")).strip() or "TokioMarine"
    requested_preset = str(form.get("create_preset", "auto")).strip().lower() or "auto"
    create_mode = str(form.get("create_mode", "core")).strip().lower() or "core"
    selected_search_algorithm = str(form.get("search_algorithm", "")).strip().upper()
    if requested_preset in {"vectordistance", "hnsw", "kmeans"}:
        create_preset = requested_preset
    elif selected_search_algorithm in {"VECTORDISTANCE", "HNSW", "KMEANS"}:
        create_preset = selected_search_algorithm.lower()
    else:
        create_preset = "vectordistance"
    doc_pipeline_mode = str(form.get("doc_pipeline_mode", "text_core")).strip().lower()
    if doc_pipeline_mode not in {"text_core", "multi_format", "multi_format_bookrag"}:
        doc_pipeline_mode = "text_core"
    create_values["vector_store_name"] = vector_store_name
    create_values["create_preset"] = create_preset
    create_values["create_mode"] = create_mode
    create_values["doc_pipeline_mode"] = doc_pipeline_mode
    for ui_field, default_value in DOC_PIPELINE_UI_DEFAULTS.items():
        ui_raw = str(form.get(ui_field, default_value)).strip()
        create_values[ui_field] = ui_raw[:CREATE_FIELD_MAX_LEN]

    create_payload: dict = {}
    warnings: list[str] = list(upload_notices)
    allowed_fields = CORE_CREATE_FIELDS if create_mode == "core" else {field["name"] for field in CREATE_FIELDS}
    for field in CREATE_FIELDS:
        field_name = field["name"]
        raw = str(form.get(field_name, "")).strip()
        if len(raw) > CREATE_FIELD_MAX_LEN:
            raw = raw[:CREATE_FIELD_MAX_LEN]
            warnings.append(f"Field [{field_name}] exceeded {CREATE_FIELD_MAX_LEN} chars and was truncated.")
        create_values[field_name] = raw
        if field_name not in allowed_fields or not raw:
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

    apply_create_preset(create_payload, create_preset, vector_store_name)
    app.state.create_form_values = create_values

    exec_payload, path_warnings = normalize_document_files_for_create(
        create_payload,
        resolve_path_hint=resolve_path_hint_fn,
    )
    warnings.extend(path_warnings)
    multi_format_summary: dict | None = None
    multi_format_error = ""
    if doc_pipeline_mode in {"multi_format", "multi_format_bookrag"}:
        try:
            exec_payload, multi_format_summary = apply_multi_format_pipeline(
                exec_payload=exec_payload,
                create_values=create_values,
                vector_store_name=vector_store_name,
                connection_params=app.state.evs_state.get("params", {}),
                execute_sql_fn=execute_sql_fn,
                resolve_path_hint=resolve_path_hint_fn,
            )
            warnings.extend(multi_format_summary.get("warnings", []))
        except Exception as ex:
            multi_format_error = str(ex)

    execution_output_preview = ""
    status_output_preview = ""

    if multi_format_error:
        result_status = "error"
        result_message = f"Step 2 failed during multi format preprocessing: {multi_format_error}"
    elif vector_store_cls is None:
        result_status = "error"
        result_message = "Step 2 failed: VectorStore runtime is unavailable in current environment."
    else:
        try:
            vector_store = vector_store_cls(vector_store_name)
            create_output = vector_store.create(**exec_payload)
            execution_output_preview = format_preview(create_output)

            status_fn = getattr(vector_store, "status", None)
            if callable(status_fn):
                try:
                    status_output_preview = format_preview(status_fn())
                except Exception as status_ex:
                    status_output_preview = f"Status check failed: {status_ex}"

            result_status = "ok_with_warnings" if warnings else "ok"
            result_message = "Step 2 completed. VectorStore.create() executed successfully."
            if multi_format_summary:
                result_message += (
                    " "
                    f"multi format chunks saved to {multi_format_summary.get('table_name')} "
                    f"({multi_format_summary.get('chunk_count')} rows from "
                    f"{multi_format_summary.get('document_count')} file(s))."
                )
        except Exception as ex:
            ex_text = str(ex)
            if is_vectorstore_already_exists_error_fn(ex_text):
                warnings.append(
                    f"VectorStore '{vector_store_name}' already exists. Skipped create() and reused existing store."
                )
                vector_store_obj = locals().get("vector_store")
                status_fn = getattr(vector_store_obj, "status", None)
                if callable(status_fn):
                    try:
                        status_output_preview = format_preview(status_fn())
                    except Exception as status_ex:
                        status_output_preview = f"Status check failed: {status_ex}"
                result_status = "ok_with_warnings"
                result_message = f"Step 2 skipped VectorStore.create(): '{vector_store_name}' already exists."
                if multi_format_summary:
                    result_message += (
                        " "
                        f"multi format chunks saved to {multi_format_summary.get('table_name')} "
                        f"({multi_format_summary.get('chunk_count')} rows from "
                        f"{multi_format_summary.get('document_count')} file(s))."
                    )
            else:
                result_status = "error"
                result_message = f"Step 2 failed while executing VectorStore.create(): {ex}"

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
        "multi_format_summary": multi_format_summary,
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
