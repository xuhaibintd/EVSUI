from __future__ import annotations

import csv
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.runtime import (
    DEBUG_UPLOAD_DIR,
    DOCUMENT_UPLOAD_DIR,
    SESSION_COOKIE_NAME,
)
from app.local_config import local_login_defaults
from app.services.precision_eval import (
    build_precision_eval_panel_context,
    build_precision_eval_prototype_context,
    build_precision_eval_report,
    resolve_precision_eval_path,
)
from app.services.bookrag_section_rules import (
    BOOKRAG_SECTION_RULES_PATH,
    save_bookrag_section_rules,
)
from app.services.unstructured_json_inspector import build_unstructured_json_inspector_context
from app.services.bookrag_document_relations import (
    BOOKRAG_DOCUMENT_RELATION_TYPES,
    delete_document_relation,
    document_relation_table_exists,
    ensure_document_relation_table,
    fetch_bookrag_documents,
    fetch_document_relations,
    save_document_relation,
    validate_document_relations,
)
from app.services.create_config import default_create_values
from app.teradata_runtime import (
    TERADATA_IMPORT_ERROR,
    VSManager,
    VectorStore,
    create_context,
    execute_sql,
    set_auth_token,
)
from app.web_support import (
    _activate_session_state,
    _append_connect_step,
    _apply_chat_list_output_to_state,
    _apply_list_output_to_state,
    _build_file_meta,
    _build_evs_reply,
    _build_home_context,
    _cleanup_context,
    _cleanup_result_detail,
    _cleanup_result_status,
    _clear_chat_list_result,
    _clear_destroy_result,
    _clear_health_result,
    _clear_list_result,
    _collect_upload_files,
    _default_evs_state,
    _derive_base_url,
    _format_preview,
    _is_logged_in,
    _is_poc_auth_configured,
    _is_valid_poc_login,
    _is_vectorstore_already_exists_error,
    _mask_token,
    _new_connect_step,
    _new_session_scope,
    _normalize_pem_filename_for_auth,
    _now_ts,
    _persist_active_session_state,
    _render_connect_panel,
    _resolve_path_hint,
    _save_document_uploads,
    _save_pem_upload,
    _session_id_from_request,
    _table_from_result,
    _verify_vectorstore_exists,
)
from app.workflows.chat_flow import handle_chat_reset, handle_chat_send
from app.workflows.create_flow import handle_upload_and_prepare_create
from app.workflows.destroy_flow import handle_destroy_selected

router = APIRouter()


def _admin_checkbox_checked(form_data, field_name: str) -> bool:
    value = form_data.get(field_name)
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "on", "yes"}


def _admin_csv_values(form_data, field_name: str) -> list[str]:
    raw_value = str(form_data.get(field_name) or "").strip()
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _build_bookrag_admin_context(rules_payload: dict, status: dict | None = None) -> dict:
    return {
        "bookrag_section_rules": rules_payload,
        "bookrag_section_rules_path": str(BOOKRAG_SECTION_RULES_PATH),
        "bookrag_section_rules_status": status,
        "unstructured_status": None,
        "json_inspector": build_unstructured_json_inspector_context(),
    }


def _build_unstructured_admin_context(app, status: dict | None = None) -> dict:
    return {
        "evs": app.state.evs_state,
        "unstructured_status": status,
        "json_inspector": build_unstructured_json_inspector_context(),
    }


def _document_relation_schema_name(app) -> str | None:
    create_values = getattr(app.state, "create_form_values", {}) or {}
    state = getattr(app.state, "evs_state", {}) or {}
    params = state.get("actual_params") or state.get("params") or {}
    return str(create_values.get("target_database") or params.get("username") or "").strip() or None


def _document_relation_admin_context(
    app,
    *,
    vector_store_name: str = "",
    status: dict | None = None,
) -> dict:
    state = app.state.evs_state
    options = list(dict.fromkeys(
        str(item).strip()
        for item in (
            list(state.get("chat_vs_options") or [])
            + [state.get("last_created_vs_name"), state.get("selected_vs_name")]
        )
        if str(item or "").strip()
    ))
    selected = str(
        vector_store_name
        or state.get("last_created_vs_name")
        or state.get("selected_vs_name")
        or ""
    ).strip()
    context = {
        "vector_store_options": options,
        "selected_vector_store": selected,
        "documents": [],
        "relations": [],
        "relation_types": list(BOOKRAG_DOCUMENT_RELATION_TYPES),
        "table_initialized": False,
        "status": status,
        "source": "database",
    }
    if not selected:
        context["documents"] = getattr(app.state, "document_uploads", [])
        context["relations"] = getattr(app.state, "document_relation_drafts", [])
        context["source"] = "upload"
        return context
    try:
        schema_name = _document_relation_schema_name(app)
        context["documents"] = fetch_bookrag_documents(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        context["table_initialized"] = document_relation_table_exists(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        if context["table_initialized"]:
            context["relations"] = fetch_document_relations(
                vector_store_name=selected,
                schema_name=schema_name,
                execute_sql_fn=execute_sql,
                active_only=False,
            )
    except Exception as ex:
        if status is None:
            context["status"] = {
                "kind": "error",
                "title": "Document Relationship Load Failed",
                "detail": str(ex),
            }
    return context

@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not _is_logged_in(request, request.app):
        return RedirectResponse(url="/login", status_code=303)
    _activate_session_state(request, request.app)
    context = _build_home_context(request, request.app)
    return request.app.state.templates.TemplateResponse(request, "index.html", context)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_logged_in(request, request.app):
        return RedirectResponse(url="/", status_code=303)
    default_username, default_password = local_login_defaults()
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "",
            "logged_in": False,
            "username": default_username,
            "password": default_password,
            "user_initials": "",
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(default=""), password: str = Form(default="")):
    clean_username = username.strip()
    if _is_valid_poc_login(clean_username, password):
        sid = uuid.uuid4().hex
        request.app.state.user_sessions[sid] = _new_session_scope(username=clean_username)
        secure_cookie = request.url.scheme == "https"
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("evsui_auth", "1", httponly=True, samesite="lax", secure=secure_cookie)
        response.set_cookie("evsui_user", clean_username, httponly=True, samesite="lax", secure=secure_cookie)
        response.set_cookie(SESSION_COOKIE_NAME, sid, httponly=True, samesite="lax", secure=secure_cookie)
        return response
    if not _is_poc_auth_configured():
        error_message = (
            "Server auth is not configured. Set POC_AUTH_FILE "
            "(or POC_ADMIN_USER / POC_ADMIN_PASSWORD)."
        )
    else:
        error_message = "Invalid username or password."
    default_username, default_password = local_login_defaults()
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error_message,
            "logged_in": False,
            "username": clean_username or default_username,
            "password": password or default_password,
            "user_initials": "",
        },
    )


@router.post("/logout")
async def logout(request: Request):
    sid = _session_id_from_request(request)
    if sid:
        request.app.state.user_sessions.pop(sid, None)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("evsui_auth")
    response.delete_cookie("evsui_user")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.post("/ui/evs/connect", response_class=HTMLResponse)
async def evs_connect(
    request: Request,
    host: str = Form(default=""),
    username: str = Form(default=""),
    password: str = Form(default=""),
    ues_url: str = Form(default=""),
    pat_token: str = Form(default=""),
    current_pem_file: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    state = request.app.state.evs_state
    steps: list[dict[str, str]] = []
    actual_params: dict = {}
    resolved_pem_path = current_pem_file.strip()
    if pem_file is not None and pem_file.filename:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix in {".pem", ".key", ".crt"}:
            resolved_pem_path = _save_pem_upload(pem_file)
            steps.append(_new_connect_step("PEM File", "ok", f"Uploaded PEM saved as: {resolved_pem_path}"))
    elif resolved_pem_path:
        resolved_existing_pem = _resolve_path_hint(resolved_pem_path)
        if resolved_existing_pem == resolved_pem_path:
            fallback_pem = str((_default_evs_state().get("params") or {}).get("pem_file") or "").strip()
            if fallback_pem and fallback_pem != resolved_pem_path:
                steps.append(
                    _new_connect_step(
                        "PEM File",
                        "warn",
                        f"Existing PEM path not found: {resolved_pem_path}. Using fallback: {fallback_pem}",
                    )
                )
                resolved_pem_path = fallback_pem
            else:
                steps.append(_new_connect_step("PEM File", "warn", f"PEM path not found: {resolved_pem_path}"))
        else:
            steps.append(_new_connect_step("PEM File", "ok", f"Using existing PEM path: {resolved_pem_path}"))
    else:
        steps.append(_new_connect_step("PEM File", "warn", "No PEM file provided."))

    params = {
        "host": host.strip(),
        "username": username.strip(),
        "password": password,
        "ues_url": ues_url.strip(),
        "pat_token": (pat_token or "").strip(),
        "pem_file": resolved_pem_path,
    }
    previous_params = state.get("params") or {}
    params["unstructured_api_url"] = str(previous_params.get("unstructured_api_url") or "").strip()
    params["unstructured_api_key"] = str(previous_params.get("unstructured_api_key") or "").strip()
    if params["pat_token"]:
        steps.append(_new_connect_step("PAT Token", "ok", f"Using submitted token: {_mask_token(params['pat_token'])}"))
    else:
        steps.append(_new_connect_step("PAT Token", "warn", "PAT token is empty. User must input it manually."))
    state["params"] = params
    steps.append(
        _new_connect_step(
            "Input Capture",
            "ok",
            f"host={params['host']}, username={params['username']}, ues_url={params['ues_url']}",
        )
    )

    missing = []
    if not params["host"]:
        missing.append("host")
    if not params["username"]:
        missing.append("username")
    if not params["password"]:
        missing.append("password")
    if not params["pat_token"]:
        missing.append("pat_token")
    if not params["ues_url"]:
        missing.append("ues_url")

    if missing:
        steps.append(_new_connect_step("Validate Required Fields", "error", f"Missing required fields: {', '.join(missing)}"))
        state["connected"] = False
        state["connected_at"] = ""
        state["last_success"] = ""
        state["last_error"] = f"Missing required fields: {', '.join(missing)}"
        _clear_health_result(state)
        _clear_list_result(state)
        _clear_chat_list_result(state)
        state["selected_vs_name"] = ""
        _clear_destroy_result(state)
        state["actual_params"] = actual_params
        state["connect_steps"] = steps
    elif not (create_context and set_auth_token and VSManager):
        steps.append(
            _new_connect_step(
                "Dependency Check",
                "error",
                f"teradataml/teradatagenai import failed: {TERADATA_IMPORT_ERROR}",
            )
        )
        state["connected"] = False
        state["connected_at"] = ""
        state["last_success"] = ""
        state["last_error"] = (
            "teradataml/teradatagenai is not available. "
            "Install them first. "
            f"Import error: {TERADATA_IMPORT_ERROR}"
        )
        _clear_health_result(state)
        _clear_list_result(state)
        _clear_chat_list_result(state)
        state["selected_vs_name"] = ""
        _clear_destroy_result(state)
        state["actual_params"] = actual_params
        state["connect_steps"] = steps
    else:
        steps.append(_new_connect_step("Validate Required Fields", "ok", "All required fields are present."))
        derived_base_url = _derive_base_url(params["ues_url"])
        steps.append(_new_connect_step("Derive Base URL", "ok", f"base_url = {derived_base_url}"))
        resolved_pem_for_auth = _resolve_path_hint(params["pem_file"])
        normalized_pem_for_auth = _normalize_pem_filename_for_auth(resolved_pem_for_auth) if resolved_pem_for_auth else ""
        pem_meta = _build_file_meta(params["pem_file"])
        warnings: list[str] = []
        if params["pem_file"] and resolved_pem_for_auth == params["pem_file"]:
            warnings.append("PEM path not found on disk; authentication will use provided raw value.")
            steps.append(
                _new_connect_step(
                    "Resolve PEM Path",
                    "warn",
                    f"PEM file not found on disk, using raw value: {params['pem_file']}",
                )
            )
        elif resolved_pem_for_auth:
            steps.append(_new_connect_step("Resolve PEM Path", "ok", f"Resolved PEM path: {resolved_pem_for_auth}"))
        else:
            steps.append(_new_connect_step("Resolve PEM Path", "warn", "No PEM path resolved."))
        if normalized_pem_for_auth and normalized_pem_for_auth != resolved_pem_for_auth:
            steps.append(
                _new_connect_step(
                    "Normalize PEM Filename",
                    "ok",
                    f"Auth will use normalized filename path: {normalized_pem_for_auth}",
                )
            )
        elif normalized_pem_for_auth:
            steps.append(
                _new_connect_step(
                    "Normalize PEM Filename",
                    "ok",
                    f"Filename already valid for auth: {normalized_pem_for_auth}",
                )
            )
        try:
            cleanup_before = _cleanup_context()
            steps.append(
                _new_connect_step(
                    "Cleanup Previous Session",
                    _cleanup_result_status(cleanup_before),
                    _cleanup_result_detail(cleanup_before),
                )
            )
            create_context(host=params["host"], username=params["username"], password=params["password"])
            steps.append(_new_connect_step("create_context", "ok", "Database context created successfully."))

            auth_kwargs = {"base_url": derived_base_url, "pat_token": params["pat_token"]}
            if normalized_pem_for_auth:
                auth_kwargs["pem_file"] = normalized_pem_for_auth
            elif resolved_pem_for_auth:
                auth_kwargs["pem_file"] = resolved_pem_for_auth
            elif params["pem_file"]:
                auth_kwargs["pem_file"] = params["pem_file"]
            actual_params = {
                "create_context": {
                    "host": params["host"],
                    "username": params["username"],
                    "password_length": len(params["password"] or ""),
                },
                "set_auth_token": auth_kwargs | {"pat_token": params["pat_token"], "pem_meta": pem_meta},
                "pem_resolution": {
                    "input": params["pem_file"],
                    "resolved": resolved_pem_for_auth,
                    "normalized": normalized_pem_for_auth,
                },
            }
            set_auth_token(**auth_kwargs)
            steps.append(_new_connect_step("set_auth_token", "ok", "VS authentication token set successfully with selected PEM."))

            state["connected"] = True
            state["connected_at"] = _now_ts()
            state["last_error"] = " | ".join(warnings) if warnings else ""
            state["last_success"] = "Step 1 completed. Database connection and VS authentication succeeded."
            _clear_health_result(state)
            _clear_list_result(state)
            _clear_chat_list_result(state)
            state["selected_vs_name"] = ""
            _clear_destroy_result(state)
            state["actual_params"] = actual_params
            steps.append(_new_connect_step("VSManager.list()", "info", "Skipped on connect. Click 'Run List' manually."))
            state["connect_steps"] = steps
        except Exception as ex:
            cleanup_after_fail = _cleanup_context()
            steps.append(_new_connect_step("Execution Failed", "error", str(ex)))
            steps.append(
                _new_connect_step(
                    "Rollback Cleanup",
                    _cleanup_result_status(cleanup_after_fail),
                    _cleanup_result_detail(cleanup_after_fail),
                )
            )
            state["connected"] = False
            state["connected_at"] = ""
            state["last_success"] = ""
            state["last_error"] = f"Connection/auth failed: {ex}"
            _clear_health_result(state)
            _clear_list_result(state)
            _clear_chat_list_result(state)
            state["selected_vs_name"] = ""
            _clear_destroy_result(state)
            state["actual_params"] = actual_params
            state["connect_steps"] = steps

    return _render_connect_panel(request, request.app)


@router.post("/ui/evs/upload-pem", response_class=HTMLResponse)
async def upload_pem_file(
    request: Request,
    current_pem_file: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    pem_file_path = current_pem_file.strip() or request.app.state.evs_state["params"].get("pem_file", "")
    pem_upload_error = ""

    if pem_file is None or not pem_file.filename:
        pem_upload_error = "No PEM file selected."
    else:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix not in {".pem", ".key", ".crt"}:
            pem_upload_error = "Only .pem, .key, .crt files are allowed."
        else:
            pem_file_path = _save_pem_upload(pem_file)
            request.app.state.evs_state["params"]["pem_file"] = pem_file_path

    _persist_active_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/pem_upload_status.html",
        {
            "pem_file_path": pem_file_path,
            "pem_upload_error": pem_upload_error,
        },
    )


@router.post("/ui/evs/reset", response_class=HTMLResponse)
async def evs_reset(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    cleanup_result = _cleanup_context()
    reset_state = _default_evs_state()
    reset_state["last_success"] = "Disconnected and reset completed."
    reset_state["connect_steps"] = [
        _new_connect_step(
            "Reset / Disconnect",
            _cleanup_result_status(cleanup_result),
            f"Reset endpoint called. {_cleanup_result_detail(cleanup_result)}",
        )
    ]
    request.app.state.evs_state = reset_state
    request.app.state.create_form_values = default_create_values()
    request.app.state.last_create_operation = None
    request.app.state.document_uploads = []
    request.app.state.document_relation_drafts = []
    request.app.state.document_upload_notices = []
    request.app.state.chat_history = []
    _persist_active_session_state(request, request.app)
    headers = getattr(request, "headers", {})
    if headers.get("HX-Request", "").lower() != "true":
        return _render_connect_panel(request, request.app)
    context = _build_home_context(request, request.app)
    context["is_htmx"] = True
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/evs_reset_response.html",
        context,
    )


@router.post("/ui/create/upload-documents", response_class=HTMLResponse)
async def upload_documents_for_create(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    form = await request.form()
    files = _collect_upload_files(form, field_name="files")

    saved: list[dict] = []
    notices: list[str] = []
    upload_error = ""
    if not files:
        upload_error = "No files selected."
    else:
        saved, notices = await _save_document_uploads(files)
        if not saved:
            upload_error = "No valid files found in selection."

    if saved:
        request.app.state.document_uploads = saved
        from app.services.bookrag_document_relations import suggest_document_relations

        request.app.state.document_relation_drafts = suggest_document_relations(saved)
    request.app.state.document_upload_notices = notices

    _persist_active_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/selected_documents.html",
        {
            "document_uploads": request.app.state.document_uploads,
            "document_relation_drafts": request.app.state.document_relation_drafts,
            "document_upload_error": upload_error,
            "document_upload_notices": notices,
        },
    )


@router.post("/ui/evs/health", response_class=HTMLResponse)
async def evs_run_health(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    state = request.app.state.evs_state
    if not state["connected"]:
        _clear_health_result(state)
        state["health_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.health()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request, request.app)
    if VSManager is None:
        _clear_health_result(state)
        state["health_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.health()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request, request.app)
    health_fn = getattr(VSManager, "health", None)
    if not callable(health_fn):
        _clear_health_result(state)
        state["health_preview"] = "Cannot run: VSManager.health is not callable."
        state["last_error"] = "VSManager.health() is not callable."
        _append_connect_step(state, "VSManager.health()", "error", "VSManager.health is missing or not callable.")
        return _render_connect_panel(request, request.app)
    try:
        health_output = health_fn()
        headers, rows_data = _table_from_result(health_output)
        state["health_columns"] = headers
        state["health_rows"] = rows_data
        state["health_row_count"] = len(rows_data)
        state["health_preview"] = _format_preview(health_output, max_chars=None)
        state["last_error"] = ""
        state["last_success"] = "VSManager.health() completed."
        _append_connect_step(state, "VSManager.health()", "ok", "Called successfully.")
    except Exception as ex:
        _clear_health_result(state)
        state["health_preview"] = f"Error: {ex}"
        state["last_error"] = f"VSManager.health() failed: {ex}"
        _append_connect_step(state, "VSManager.health()", "error", f"Execution failed: {ex}")
    return _render_connect_panel(request, request.app)


@router.post("/ui/evs/list", response_class=HTMLResponse)
async def evs_run_list(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    state = request.app.state.evs_state
    _clear_destroy_result(state)
    if not state["connected"]:
        _clear_list_result(state)
        state["list_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.list()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request, request.app)
    if VSManager is None:
        _clear_list_result(state)
        state["list_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.list()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request, request.app)
    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        _clear_list_result(state)
        state["list_preview"] = "Cannot run: VSManager.list is not callable."
        state["last_error"] = "VSManager.list() is not callable."
        _append_connect_step(state, "VSManager.list()", "error", "VSManager.list is missing or not callable.")
        return _render_connect_panel(request, request.app)
    try:
        list_output = list_fn()
        visible_rows, total_rows, username_filter = _apply_list_output_to_state(
            state,
            list_output,
            sync_chat_options=False,
        )
        state["list_loaded_by_user"] = True
        if total_rows is not None:
            if username_filter:
                _append_connect_step(
                    state,
                    "VSManager.list()",
                    "ok",
                    f"Called successfully. rows={visible_rows}/{total_rows} (filtered by username='{username_filter}').",
                )
            else:
                _append_connect_step(state, "VSManager.list()", "ok", f"Called successfully. rows={total_rows}.")
        else:
            _append_connect_step(state, "VSManager.list()", "ok", "Called successfully.")
        state["last_error"] = ""
        state["last_success"] = "VSManager.list() completed."
    except Exception as ex:
        _clear_list_result(state)
        state["list_preview"] = f"Error: {ex}"
        state["last_error"] = f"VSManager.list() failed: {ex}"
        _append_connect_step(state, "VSManager.list()", "error", f"Execution failed: {ex}")
    return _render_connect_panel(request, request.app)


@router.post("/ui/chat/vs-list", response_class=HTMLResponse)
async def chat_run_list(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    state = request.app.state.evs_state
    if not state["connected"]:
        _clear_chat_list_result(state)
        state["chat_list_preview"] = "Connect in Step 1 first."
        _persist_active_session_state(request, request.app)
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/chat_vector_store_list.html",
            {"evs": state, "is_oob": False},
        )

    if VSManager is None:
        _clear_chat_list_result(state)
        state["chat_list_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        _persist_active_session_state(request, request.app)
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/chat_vector_store_list.html",
            {"evs": state, "is_oob": False},
        )

    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        _clear_chat_list_result(state)
        state["chat_list_preview"] = "Cannot run: VSManager.list is not callable."
        _persist_active_session_state(request, request.app)
        return request.app.state.templates.TemplateResponse(
            request,
            "partials/chat_vector_store_list.html",
            {"evs": state, "is_oob": False},
        )

    try:
        list_output = list_fn()
        visible_rows, total_rows, username_filter = _apply_chat_list_output_to_state(state, list_output)
        if total_rows is not None:
            if username_filter:
                _append_connect_step(
                    state,
                    "Step 3 VSManager.list()",
                    "ok",
                    f"Called successfully. rows={visible_rows}/{total_rows} (filtered by username='{username_filter}').",
                )
            else:
                _append_connect_step(state, "Step 3 VSManager.list()", "ok", f"Called successfully. rows={total_rows}.")
        else:
            _append_connect_step(state, "Step 3 VSManager.list()", "ok", "Called successfully.")
        state["last_error"] = ""
        state["last_success"] = "Step 3 Run List completed."
    except Exception as ex:
        _clear_chat_list_result(state)
        state["chat_list_preview"] = f"Error: {ex}"
        state["last_error"] = f"Step 3 Run List failed: {ex}"
        _append_connect_step(state, "Step 3 VSManager.list()", "error", f"Execution failed: {ex}")

    _persist_active_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/chat_vector_store_list.html",
        {"evs": state, "is_oob": False},
    )


@router.post("/ui/evs/select", response_class=HTMLResponse)
async def evs_select_from_list(request: Request, vs_name: str = Form(default="")):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    state = request.app.state.evs_state
    selected_name = (vs_name or str(request.query_params.get("vs_name", ""))).strip()
    state["selected_vs_name"] = selected_name
    state["destroy_status"] = "neutral"
    if selected_name:
        state["destroy_preview"] = f"Selected '{selected_name}'. Click Delete to delete."
        _append_connect_step(state, "Vector Store selection", "ok", f"Selected '{selected_name}'.")
    else:
        state["destroy_preview"] = "Click a row in list, then destroy it here."
        _append_connect_step(state, "Vector Store selection", "warn", "Selection payload was empty.")
    return _render_connect_panel(request, request.app)


@router.post("/ui/evs/destroy", response_class=HTMLResponse)
async def evs_destroy_selected(request: Request, vs_name: str = Form(default="")):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    return await handle_destroy_selected(
        request,
        request.app.state.evs_state,
        vs_name,
        vector_store_cls=VectorStore,
        vs_manager=VSManager,
        execute_sql_fn=execute_sql,
        teradata_import_error=TERADATA_IMPORT_ERROR,
        render_connect_panel=lambda req: _render_connect_panel(req, request.app),
        append_connect_step=_append_connect_step,
    )


@router.post("/ui/create/upload", response_class=HTMLResponse)
async def upload_and_prepare_create(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    response = await handle_upload_and_prepare_create(
        request,
        request.app,
        request.app.state.templates,
        vector_store_cls=VectorStore,
        execute_sql_fn=execute_sql,
        save_document_uploads_fn=_save_document_uploads,
        collect_upload_files_fn=_collect_upload_files,
        resolve_path_hint_fn=_resolve_path_hint,
        now_ts=_now_ts,
        is_htmx=is_htmx,
        is_vectorstore_already_exists_error_fn=_is_vectorstore_already_exists_error,
        verify_vectorstore_exists_fn=_verify_vectorstore_exists,
        append_connect_step=_append_connect_step,
    )
    _persist_active_session_state(request, request.app)
    return response


@router.post("/ui/chat", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    message: str = Form(...),
    validation_target: str = Form(default="vectorstore.ask"),
    selected_vs_name: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    response = await handle_chat_send(
        request,
        request.app,
        request.app.state.templates,
        message=message,
        validation_target=validation_target,
        selected_vs_name=selected_vs_name,
        build_evs_reply=_build_evs_reply,
    )
    _persist_active_session_state(request, request.app)
    return response


@router.post("/ui/chat/reset", response_class=HTMLResponse)
async def chat_reset(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    response = await handle_chat_reset(request, request.app, request.app.state.templates)
    _persist_active_session_state(request, request.app)
    return response


@router.get("/ui/eval/panel", response_class=HTMLResponse)
async def precision_eval_panel(
    request: Request,
    pdf_path: str = "",
    json_path: str = "",
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/precision_eval_panel.html",
        {
            "eval_panel": build_precision_eval_panel_context(document_root=DOCUMENT_UPLOAD_DIR, debug_root=DEBUG_UPLOAD_DIR, selected_pdf_path=pdf_path, selected_json_path=json_path),
            "precision_eval_prototype": build_precision_eval_prototype_context(),
            "precision_eval_result": None,
        },
    )


@router.post("/ui/eval/run", response_class=HTMLResponse)
async def run_precision_eval(
    request: Request,
    pdf_path: str = Form(default=""),
    json_path: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    try:
        resolved_pdf_path = resolve_precision_eval_path(
            pdf_path,
            allowed_root=DOCUMENT_UPLOAD_DIR,
            expected_suffixes={".pdf"},
        )
        resolved_json_path = resolve_precision_eval_path(
            json_path,
            allowed_root=DEBUG_UPLOAD_DIR,
            expected_suffixes={".json"},
        )
        precision_eval_result = build_precision_eval_report(
            pdf_path=resolved_pdf_path,
            json_path=resolved_json_path,
        )
    except Exception as ex:
        precision_eval_result = {
            "error": str(ex),
            "pdf_path": str(pdf_path or "").strip(),
            "json_path": str(json_path or "").strip(),
        }

    return request.app.state.templates.TemplateResponse(
        request,
        "partials/precision_eval_result.html",
        {"precision_eval_result": precision_eval_result},
    )


@router.post("/ui/admin/bookrag-section-rules", response_class=HTMLResponse)
async def update_bookrag_section_rules_panel(request: Request):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    form_data = await request.form()
    chapter_pattern_count = max(0, int(str(form_data.get("chapter_pattern_count") or "0").strip() or "0"))
    chapter_patterns: list[dict[str, object]] = []
    for index in range(chapter_pattern_count):
        pattern = str(form_data.get(f"chapter_pattern_{index}") or "").strip()
        name = str(form_data.get(f"chapter_name_{index}") or "").strip()
        if not pattern and not name:
            continue
        chapter_patterns.append(
            {
                "name": name or f"rule_{index + 1}",
                "pattern": pattern,
                "level": max(1, int(str(form_data.get(f"chapter_level_{index}") or "1").strip() or "1")),
                "family": str(form_data.get(f"chapter_family_{index}") or "chapter").strip() or "chapter",
                "enabled": _admin_checkbox_checked(form_data, f"chapter_enabled_{index}"),
                "priority": int(str(form_data.get(f"chapter_priority_{index}") or ((index + 1) * 10)).strip() or ((index + 1) * 10)),
            }
        )

    submitted_rules = {
        "version": 1,
        "updated_at": "",
        "profiles": {
            "jp": {
                "chapter_patterns": chapter_patterns,
                "numeric_pattern": str(form_data.get("numeric_pattern") or "").strip(),
                "enum_heading_pattern": str(form_data.get("enum_heading_pattern") or "").strip(),
                "alpha_section_pattern": str(form_data.get("alpha_section_pattern") or "").strip(),
                "bracket_section_pattern": str(form_data.get("bracket_section_pattern") or "").strip(),
                "note_pattern": str(form_data.get("note_pattern") or "").strip(),
                "table_html_pattern": str(form_data.get("table_html_pattern") or "").strip(),
                "heading_tag_pattern": str(form_data.get("heading_tag_pattern") or "").strip(),
                "header_footer_types": _admin_csv_values(form_data, "header_footer_types"),
                "major_section_families": _admin_csv_values(form_data, "major_section_families"),
                "group_section_families": _admin_csv_values(form_data, "group_section_families"),
                "enum_section_families": _admin_csv_values(form_data, "enum_section_families"),
                "fullwidth_numeric_source": str(form_data.get("fullwidth_numeric_source") or "").strip(),
                "fullwidth_numeric_target": str(form_data.get("fullwidth_numeric_target") or "").strip(),
            }
        },
    }

    try:
        saved_rules = save_bookrag_section_rules(submitted_rules)
        status = {
            "kind": "ok",
            "title": "Rules Saved",
            "detail": f"Saved BookRAG section rules to {BOOKRAG_SECTION_RULES_PATH}.",
        }
        context = _build_bookrag_admin_context(saved_rules, status=status)
        context["evs"] = request.app.state.evs_state
    except Exception as ex:
        status = {
            "kind": "error",
            "title": "Save Failed",
            "detail": str(ex),
        }
        context = _build_bookrag_admin_context(submitted_rules, status=status)
        context["evs"] = request.app.state.evs_state

    return request.app.state.templates.TemplateResponse(
        request,
        "partials/bookrag_admin_panel.html",
        context,
    )



@router.get("/ui/admin/document-relations", response_class=HTMLResponse)
async def load_document_relations_admin(request: Request, vector_store_name: str = ""):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/document_relation_admin.html",
        {"document_relation_admin": _document_relation_admin_context(
            request.app,
            vector_store_name=vector_store_name,
        )},
    )


@router.post("/ui/admin/document-relations/initialize", response_class=HTMLResponse)
async def initialize_document_relations_admin(
    request: Request,
    vector_store_name: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    selected = vector_store_name.strip()
    try:
        schema_name = _document_relation_schema_name(request.app)
        documents = fetch_bookrag_documents(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        if not documents:
            raise RuntimeError("bdoc contains no documents; bdrel was not initialized.")
        created = ensure_document_relation_table(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        status = {
            "kind": "ok",
            "title": "bdrel Ready",
            "detail": "Created the document relationship table." if created else "The document relationship table already exists.",
        }
    except Exception as ex:
        status = {"kind": "error", "title": "bdrel Initialization Failed", "detail": str(ex)}
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/document_relation_admin.html",
        {"document_relation_admin": _document_relation_admin_context(
            request.app,
            vector_store_name=selected,
            status=status,
        )},
    )


@router.post("/ui/admin/document-relations/save", response_class=HTMLResponse)
async def save_document_relations_admin(
    request: Request,
    vector_store_name: str = Form(default=""),
    from_doc_id: str = Form(default=""),
    relation_type: str = Form(default=""),
    to_doc_id: str = Form(default=""),
    relation_description: str = Form(default=""),
    is_active: str = Form(default=""),
    original_from_doc_id: str = Form(default=""),
    original_relation_type: str = Form(default=""),
    original_to_doc_id: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    selected = vector_store_name.strip()
    try:
        schema_name = _document_relation_schema_name(request.app)
        documents = fetch_bookrag_documents(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        saved = save_document_relation(
            vector_store_name=selected,
            schema_name=schema_name,
            relation={
                "from_doc_id": from_doc_id,
                "relation_type": relation_type,
                "to_doc_id": to_doc_id,
                "relation_description": relation_description,
                "source_type": "human",
                "confidence": 1.0,
                "is_active": is_active,
                "confirmed": True,
            },
            documents=documents,
            execute_sql_fn=execute_sql,
            username=str(request.cookies.get("evsui_user", "")),
            original_key=(
                original_from_doc_id.strip(),
                original_relation_type.strip(),
                original_to_doc_id.strip(),
            )
            if all((original_from_doc_id.strip(), original_relation_type.strip(), original_to_doc_id.strip()))
            else None,
        )
        status = {
            "kind": "ok",
            "title": "Relationship Saved",
            "detail": f"Saved {saved['relation_type']} between the selected documents.",
        }
    except Exception as ex:
        status = {"kind": "error", "title": "Relationship Save Failed", "detail": str(ex)}
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/document_relation_admin.html",
        {"document_relation_admin": _document_relation_admin_context(
            request.app,
            vector_store_name=selected,
            status=status,
        )},
    )


@router.post("/ui/admin/document-relations/delete", response_class=HTMLResponse)
async def delete_document_relations_admin(
    request: Request,
    vector_store_name: str = Form(default=""),
    from_doc_id: str = Form(default=""),
    relation_type: str = Form(default=""),
    to_doc_id: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    selected = vector_store_name.strip()
    try:
        delete_document_relation(
            vector_store_name=selected,
            schema_name=_document_relation_schema_name(request.app),
            from_doc_id=from_doc_id.strip(),
            relation_type=relation_type.strip(),
            to_doc_id=to_doc_id.strip(),
            execute_sql_fn=execute_sql,
        )
        status = {"kind": "ok", "title": "Relationship Deleted", "detail": "The relationship was deleted."}
    except Exception as ex:
        status = {"kind": "error", "title": "Relationship Delete Failed", "detail": str(ex)}
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/document_relation_admin.html",
        {"document_relation_admin": _document_relation_admin_context(
            request.app,
            vector_store_name=selected,
            status=status,
        )},
    )


@router.get("/ui/admin/document-relations/export")
async def export_document_relations_admin(request: Request, vector_store_name: str = ""):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    selected = vector_store_name.strip()
    rows = fetch_document_relations(
        vector_store_name=selected,
        schema_name=_document_relation_schema_name(request.app),
        execute_sql_fn=execute_sql,
        active_only=False,
    )
    fieldnames = [
        "from_doc_id",
        "from_filename",
        "relation_type",
        "to_doc_id",
        "to_filename",
        "relation_description",
        "source_type",
        "confidence",
        "is_active",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{selected}_bdrel.csv"'},
    )


@router.post("/ui/admin/document-relations/import", response_class=HTMLResponse)
async def import_document_relations_admin(
    request: Request,
    vector_store_name: str = Form(default=""),
    relation_csv: UploadFile = File(default=None),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    selected = vector_store_name.strip()
    try:
        if relation_csv is None or not relation_csv.filename:
            raise ValueError("Select a document relationship CSV file.")
        payload = (await relation_csv.read()).decode("utf-8-sig")
        imported = [dict(row) for row in csv.DictReader(io.StringIO(payload))]
        schema_name = _document_relation_schema_name(request.app)
        documents = fetch_bookrag_documents(
            vector_store_name=selected,
            schema_name=schema_name,
            execute_sql_fn=execute_sql,
        )
        filename_map: dict[str, str] = {}
        duplicate_filenames: set[str] = set()
        for document in documents:
            filename = str(document["filename"])
            if filename in filename_map:
                duplicate_filenames.add(filename)
            filename_map[filename] = str(document["doc_id"])
        for row in imported:
            if not str(row.get("from_doc_id") or "").strip():
                filename = str(row.get("from_filename") or "").strip()
                if filename in duplicate_filenames or filename not in filename_map:
                    raise ValueError(f"Source filename is missing or not unique: {filename!r}.")
                row["from_doc_id"] = filename_map[filename]
            if not str(row.get("to_doc_id") or "").strip():
                filename = str(row.get("to_filename") or "").strip()
                if filename in duplicate_filenames or filename not in filename_map:
                    raise ValueError(f"Target filename is missing or not unique: {filename!r}.")
                row["to_doc_id"] = filename_map[filename]
            row["source_type"] = "import"
            row["confirmed"] = True
        normalized_rows = validate_document_relations(imported, documents)
        for row in normalized_rows:
            save_document_relation(
                vector_store_name=selected,
                schema_name=schema_name,
                relation={**row, "confirmed": True},
                documents=documents,
                execute_sql_fn=execute_sql,
                username=str(request.cookies.get("evsui_user", "")),
            )
        status = {
            "kind": "ok",
            "title": "Relationship CSV Imported",
            "detail": f"Validated and saved {len(normalized_rows)} relationship row(s).",
        }
    except Exception as ex:
        status = {"kind": "error", "title": "Relationship CSV Import Failed", "detail": str(ex)}
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/document_relation_admin.html",
        {"document_relation_admin": _document_relation_admin_context(
            request.app,
            vector_store_name=selected,
            status=status,
        )},
    )


@router.get("/ui/admin/json-inspector", response_class=HTMLResponse)
async def inspect_unstructured_json_file(
    request: Request,
    json_file: str = "",
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/unstructured_json_inspector_result.html",
        {"json_inspector": build_unstructured_json_inspector_context(json_file.strip())},
    )

@router.post("/ui/admin/unstructured-config", response_class=HTMLResponse)
async def update_unstructured_config_panel(
    request: Request,
    unstructured_api_url: str = Form(default=""),
    unstructured_api_key: str = Form(default=""),
):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)

    state = request.app.state.evs_state
    params = state.setdefault("params", {})
    params["unstructured_api_url"] = unstructured_api_url.strip()
    params["unstructured_api_key"] = (unstructured_api_key or "").strip()
    _persist_active_session_state(request, request.app)

    status = {
        "kind": "ok",
        "title": "Saved",
        "detail": "Unstructured IO account saved for the current session.",
    }
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/bookrag_admin_panel.html",
        _build_unstructured_admin_context(request.app, status=status),
    )
