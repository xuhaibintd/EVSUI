from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.session_state import (
    activate_session_state,
    current_user,
    default_evs_state,
    is_logged_in,
    is_poc_auth_configured,
    is_valid_poc_login,
    load_auth_users,
    load_connect_defaults,
    new_session_scope,
    persist_active_session_state,
    session_id_from_request,
    user_initials,
)
from app.services.create_config import (
    build_create_ui_sections,
    build_text_core_ui_fields,
    default_create_values,
)
from app.services.doc_modes.common import build_multi_format_bookrag_ui_fields, build_multi_format_ui_fields
from app.services.doc_modes.registry import DOC_PIPELINE_OPTIONS
from app.services.bookrag_retrieval import retrieve_bookrag_evidence
from app.utils.table_state import (
    apply_chat_list_output_to_state,
    apply_list_output_to_state,
    build_file_meta,
    chunk_table_sql_for_vs,
    clear_chat_list_result,
    clear_destroy_result,
    clear_health_result,
    clear_list_result,
    destroy_output_indicates_failure,
    find_list_row_for_vs,
    find_vs_row_by_name,
    format_preview,
    guess_latest_vs_name,
    is_content_based_vs_row,
    normalize_header_key,
    row_value_by_header,
    table_from_result,
)
from app.utils.uploads import (
    collect_upload_files,
    latest_uploaded_pem_relative,
    normalize_pem_filename_for_auth,
    resolve_path_hint,
    save_document_uploads,
    save_pem_upload,
)
from app.workflows.chat_flow import handle_chat_reset, handle_chat_send
from app.workflows.create_flow import handle_upload_and_prepare_create
from app.workflows.destroy_flow import handle_destroy_selected

try:
    from teradataml import create_context, remove_context
except Exception as ex:  # pragma: no cover - dependency/runtime specific.
    create_context = None
    remove_context = None
    _teradataml_core_error = str(ex)
else:
    _teradataml_core_error = ""

try:
    from teradataml import execute_sql
except Exception:
    execute_sql = None

try:
    from teradatagenai import VSManager, set_auth_token
except Exception as ex:  # pragma: no cover - dependency/runtime specific.
    VSManager = None
    set_auth_token = None
    _teradatagenai_error = str(ex)
else:
    _teradatagenai_error = ""

TERADATA_IMPORT_ERROR = " | ".join(
    part for part in (_teradataml_core_error, _teradatagenai_error) if part
)

try:
    from teradatagenai import VectorStore
except Exception:
    VectorStore = None

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = PROJECT_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENT_UPLOAD_DIR = UPLOAD_DIR / "documents"
DOCUMENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PEM_UPLOAD_DIR = UPLOAD_DIR / "pem"
PEM_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VS_BASICS_DIR = PROJECT_DIR.parent / "VS_Basics_Full_Kit"
DEFAULT_PAT_TOKEN = "<redacted-pat-token>"
DEFAULT_CHAT_VS_NAME = "TokioMarine_test"
AUTH_USERS_FILE_DEFAULT = BASE_DIR / "config" / "auth_users.json"
SESSION_COOKIE_NAME = "evsui_sid"
DEFAULT_LOGIN_USERNAME = "admin"
DEFAULT_LOGIN_PASSWORD = "<redacted-password>"
logger = logging.getLogger("evsui.connect")
logger.setLevel(logging.INFO)

JP_KANA_RE = re.compile(r"[\u3040-\u30ff]")
LATIN_RE = re.compile(r"[A-Za-z]")
HAN_RE = re.compile(r"[\u4e00-\u9fff]")

class BookRAGRetrieveRequest(BaseModel):
    question: str
    vector_store_name: str | None = None
    schema_name: str | None = None

def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _is_vectorstore_already_exists_error(raw_error: str) -> bool:
    text = str(raw_error or "").lower()
    if "already exists" not in text and "already exist" not in text:
        return False
    vectorstore_markers = (
        "vector store",
        "vectorstore",
        "vector-store",
    )
    return any(marker in text for marker in vectorstore_markers)


def _verify_vectorstore_exists(vector_store_name: str) -> tuple[bool, str, str]:
    target = str(vector_store_name or "").strip()
    if not target:
        return False, "", "empty vector store name"
    if VSManager is None:
        return False, "", "VSManager runtime is unavailable"

    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        return False, "", "VSManager.list() is not callable"

    try:
        list_output = list_fn(return_type="json")
    except Exception as ex:
        return False, "", str(ex)

    headers, rows = _table_from_result(list_output)
    matched_row = _find_vs_row_by_name(headers, rows, target)
    if matched_row:
        owner = _row_value_by_header(headers, matched_row, ("username", "user", "owner", "creator", "createdby"))
        database = _row_value_by_header(headers, matched_row, ("database", "schema", "targetdatabase"))
        permission = _row_value_by_header(headers, matched_row, ("permission", "role", "access"))
        detail_parts = []
        if owner:
            detail_parts.append(f"owner='{owner}'")
        if database:
            detail_parts.append(f"database='{database}'")
        if permission:
            detail_parts.append(f"permission='{permission}'")
        detail = ", ".join(detail_parts) if detail_parts else f"row={_format_preview(dict(zip(headers[1:], matched_row[1:])), max_chars=300)}"
        return True, f"VSManager.list() confirmed '{target}' exists ({detail}).", ""
    return False, f"VSManager.list() did not contain '{target}'.", ""


_normalize_header_key = normalize_header_key
_find_list_row_for_vs = find_list_row_for_vs
_find_vs_row_by_name = find_vs_row_by_name
_destroy_output_indicates_failure = destroy_output_indicates_failure
_row_value_by_header = row_value_by_header
_is_content_based_vs_row = is_content_based_vs_row
_chunk_table_sql_for_vs = chunk_table_sql_for_vs
_table_from_result = table_from_result


def _derive_base_url(ues_url: str) -> str:
    src = ues_url.strip()
    # strip off the trailing /open-analytics
    if src.endswith("/open-analytics"):
        return src[:-15]
    return src


def _save_pem_upload(pem_file: UploadFile) -> str:
    return save_pem_upload(pem_file, PEM_UPLOAD_DIR, PROJECT_DIR)


def _latest_uploaded_pem_relative() -> str:
    return latest_uploaded_pem_relative(PEM_UPLOAD_DIR, PROJECT_DIR)


def _collect_upload_files(form_data, field_name: str = "files") -> list[UploadFile]:
    return collect_upload_files(form_data, field_name)


async def _save_document_uploads(files: list[UploadFile]) -> tuple[list[dict], list[str]]:
    return await save_document_uploads(files, DOCUMENT_UPLOAD_DIR, PROJECT_DIR, _now_ts)


def _resolve_path_hint(path_hint: str) -> str:
    return resolve_path_hint(path_hint, PROJECT_DIR, VS_BASICS_DIR)


def _normalize_pem_filename_for_auth(resolved_pem_path: str) -> str:
    return normalize_pem_filename_for_auth(resolved_pem_path)


def _cleanup_context() -> dict[str, str]:
    result = {
        "vs_disconnect": "skipped (VSManager unavailable)",
        "remove_context": "skipped (remove_context unavailable)",
    }
    if VSManager is not None:
        try:
            VSManager.disconnect(raise_error=False)
            result["vs_disconnect"] = "called"
        except Exception:
            result["vs_disconnect"] = "error"
    if remove_context is not None:
        try:
            remove_context()
            result["remove_context"] = "called"
        except Exception:
            result["remove_context"] = "error"
    return result


def _cleanup_result_status(cleanup_result: dict[str, str]) -> str:
    if cleanup_result.get("vs_disconnect") == "error" or cleanup_result.get("remove_context") == "error":
        return "warn"
    return "ok"


def _cleanup_result_detail(cleanup_result: dict[str, str]) -> str:
    return (
        f"VSManager.disconnect(): {cleanup_result.get('vs_disconnect', 'skipped')}; "
        f"remove_context(): {cleanup_result.get('remove_context', 'skipped')}."
    )


_format_preview = format_preview
_apply_list_output_to_state = apply_list_output_to_state
_apply_chat_list_output_to_state = apply_chat_list_output_to_state
_clear_list_result = clear_list_result
_clear_chat_list_result = clear_chat_list_result
_clear_health_result = clear_health_result
_clear_destroy_result = clear_destroy_result


def _build_file_meta(path_hint: str) -> dict[str, str | int | bool]:
    return build_file_meta(path_hint, _resolve_path_hint)


def _new_connect_step(step: str, status: str, detail: str) -> dict[str, str]:
    status_lower = status.lower()
    message = f"[{step}] {detail}"
    if status_lower == "error":
        logger.error(message)
    elif status_lower == "warn":
        logger.warning(message)
    else:
        logger.info(message)
    return {
        "time": datetime.now().strftime("%H:%M:%S"),
        "step": step,
        "status": status,
        "detail": detail,
    }


def _append_connect_step(state: dict, step: str, status: str, detail: str, limit: int = 120) -> None:
    steps = list(state.get("connect_steps", []))
    steps.append(_new_connect_step(step, status, detail))
    state["connect_steps"] = steps[-limit:]


def _mask_token(token: str) -> str:
    value = token.strip()
    if not value:
        return "<empty>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _load_connect_defaults() -> dict[str, str]:
    return load_connect_defaults(_latest_uploaded_pem_relative, VS_BASICS_DIR, DEFAULT_PAT_TOKEN)


def _default_evs_state() -> dict:
    return default_evs_state(_load_connect_defaults)


app = FastAPI(title="Teradata Vector Store", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.state.user_sessions: dict[str, dict] = {}
app.state.evs_state = _default_evs_state()
app.state.create_form_values = default_create_values()
app.state.last_create_operation = None
app.state.document_uploads = []
app.state.document_upload_notices = []
app.state.chat_history = []


def _new_session_scope(username: str = "") -> dict:
    return new_session_scope(username, _default_evs_state, default_create_values)


def _session_id_from_request(request: Request) -> str:
    return session_id_from_request(request, SESSION_COOKIE_NAME)


def _activate_session_state(request: Request) -> dict:
    return activate_session_state(
        request,
        app,
        SESSION_COOKIE_NAME,
        _default_evs_state,
        default_create_values,
    )


def _persist_active_session_state(request: Request) -> None:
    persist_active_session_state(request, app, SESSION_COOKIE_NAME)


def _load_auth_users() -> dict[str, str]:
    return load_auth_users(AUTH_USERS_FILE_DEFAULT, logger)


def _active_vector_store_name() -> str:
    state = app.state.evs_state or {}
    selected = str(state.get("selected_vs_name", "")).strip()
    return selected or DEFAULT_CHAT_VS_NAME


def _detect_message_language(text: str) -> str:
    # Product language priority: Japanese first, then English.
    if JP_KANA_RE.search(text):
        return "ja"
    if HAN_RE.search(text):
        return "ja"
    if LATIN_RE.search(text):
        return "en"
    return "en"


def _ask_prompt_for_language(lang: str) -> str:
    if lang == "ja":
        return (
            "Answer only with evidence from retrieved documents. "
            "Respond in Japanese only. "
            "If evidence is missing, explicitly state that in Japanese."
        )
    return (
        "Answer only with evidence from retrieved documents. "
        "Use exactly the same language as the user's question. "
        "If evidence is missing, state that clearly in the same language."
    )


def _build_evs_reply(message: str, validation_target: str, vector_store_name: str = "") -> str:
    if VectorStore is None:
        return "Validation failed: VectorStore runtime is unavailable."

    question = message.strip()
    try:
        lang = _detect_message_language(question)
    except re.error:
        lang = "en"
    ask_prompt = _ask_prompt_for_language(lang)
    target = validation_target.strip().lower()
    vs_name = str(vector_store_name or "").strip()
    if not vs_name:
        return "Validation failed: no vector store selected. Click 'Run List' and choose one."

    try:
        vector_store = VectorStore(vs_name)
    except Exception as ex:
        return f"Validation failed: cannot open VectorStore('{vs_name}'): {ex}"

    try:
        if target == "vectorstore.similarity_search":
            try:
                result = vector_store.similarity_search(question=question)
            except TypeError:
                result = vector_store.similarity_search(question)
            return _format_preview(result, max_chars=None)

        try:
            result = vector_store.ask(question=question, prompt=ask_prompt)
        except TypeError:
            try:
                result = vector_store.ask(question, ask_prompt)
            except TypeError:
                try:
                    result = vector_store.ask(question=question)
                except TypeError:
                    result = vector_store.ask(question)
        return _format_preview(result, max_chars=None)
    except Exception as ex:
        method_name = "similarity_search" if target == "vectorstore.similarity_search" else "ask"
        return f"{method_name} failed on '{vs_name}': {ex}"


def _build_bookrag_chat_reply(evidence: dict | None, vector_store_name: str) -> str:
    vs_name = str(vector_store_name or "").strip()
    evidence_text = str((evidence or {}).get("evidence_text") or "").strip()
    if evidence_text:
        return f"BookRAG evidence for '{vs_name}':\n\n{evidence_text}"

    similarity_row_count = 0
    package_count = 0
    try:
        similarity_row_count = int((evidence or {}).get("similarity_row_count") or 0)
    except Exception:
        similarity_row_count = 0
    try:
        package_count = int((evidence or {}).get("package_count") or 0)
    except Exception:
        package_count = 0
    headers = (evidence or {}).get("similarity_headers") or []
    header_preview = ", ".join(str(item).strip() for item in headers[:6] if str(item).strip())
    similarity_preview = str((evidence or {}).get("similarity_preview") or "").strip()

    if vs_name:
        message = f"No BookRAG evidence found for '{vs_name}'."
    else:
        message = "No BookRAG evidence found."

    diagnostics: list[str] = []
    if similarity_row_count:
        diagnostics.append(f"similarity_rows={similarity_row_count}")
    if package_count:
        diagnostics.append(f"packages={package_count}")
    if header_preview:
        diagnostics.append(f"headers=[{header_preview}]")
    if similarity_preview:
        diagnostics.append(f"preview={similarity_preview}")
    if diagnostics:
        message += " " + " ".join(diagnostics) + "."
    return message


def _current_user(request: Request) -> str:
    return current_user(request)


def _user_initials(username: str) -> str:
    return user_initials(username)


def _build_home_context(request: Request) -> dict:
    _activate_session_state(request)
    state = app.state.evs_state

    username = _current_user(request)
    return {
        "messages": app.state.chat_history,
        "evs": state,
        "create_ui_sections": build_create_ui_sections(),
        "text_core_ui_fields": build_text_core_ui_fields(),
        "multi_format_ui_fields": build_multi_format_ui_fields(),
        "multi_format_bookrag_ui_fields": build_multi_format_bookrag_ui_fields(),
        "create_values": app.state.create_form_values,
        "doc_pipeline_options": DOC_PIPELINE_OPTIONS,
        "create_result": app.state.last_create_operation,
        "document_uploads": app.state.document_uploads,
        "document_upload_error": "",
        "document_upload_notices": app.state.document_upload_notices,
        "logged_in": _is_logged_in(request),
        "username": username,
        "user_initials": _user_initials(username),
    }


def _render_connect_panel(request: Request):
    _persist_active_session_state(request)
    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    return templates.TemplateResponse(
        request,
        "partials/evs_connect_panel.html",
        {"evs": app.state.evs_state, "is_htmx": is_htmx},
    )


def _is_logged_in(request: Request) -> bool:
    return is_logged_in(request, app, SESSION_COOKIE_NAME)


def _is_poc_auth_configured() -> bool:
    return is_poc_auth_configured(_load_auth_users)


def _is_valid_poc_login(username: str, password: str) -> bool:
    return is_valid_poc_login(username, password, _load_auth_users)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if not _is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    _activate_session_state(request)
    context = _build_home_context(request)
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_logged_in(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "",
            "logged_in": False,
            "username": DEFAULT_LOGIN_USERNAME,
            "password": DEFAULT_LOGIN_PASSWORD,
            "user_initials": "",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(default=""), password: str = Form(default="")):
    clean_username = username.strip()
    if _is_valid_poc_login(clean_username, password):
        sid = uuid.uuid4().hex
        app.state.user_sessions[sid] = _new_session_scope(username=clean_username)
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
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error_message,
            "logged_in": False,
            "username": clean_username or DEFAULT_LOGIN_USERNAME,
            "password": password or DEFAULT_LOGIN_PASSWORD,
            "user_initials": "",
        },
    )


@app.post("/logout")
async def logout(request: Request):
    sid = _session_id_from_request(request)
    if sid:
        app.state.user_sessions.pop(sid, None)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("evsui_auth")
    response.delete_cookie("evsui_user")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.post("/ui/evs/connect", response_class=HTMLResponse)
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
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    state = app.state.evs_state
    steps: list[dict[str, str]] = []
    actual_params: dict = {}
    resolved_pem_path = current_pem_file.strip()
    if pem_file is not None and pem_file.filename:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix in {".pem", ".key", ".crt"}:
            resolved_pem_path = _save_pem_upload(pem_file)
            steps.append(_new_connect_step("PEM File", "ok", f"Uploaded PEM saved as: {resolved_pem_path}"))
    elif resolved_pem_path:
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

    return _render_connect_panel(request)


@app.post("/ui/evs/upload-pem", response_class=HTMLResponse)
async def upload_pem_file(
    request: Request,
    current_pem_file: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)

    pem_file_path = current_pem_file.strip() or app.state.evs_state["params"].get("pem_file", "")
    pem_upload_error = ""

    if pem_file is None or not pem_file.filename:
        pem_upload_error = "No PEM file selected."
    else:
        suffix = Path(pem_file.filename).suffix.lower()
        if suffix not in {".pem", ".key", ".crt"}:
            pem_upload_error = "Only .pem, .key, .crt files are allowed."
        else:
            pem_file_path = _save_pem_upload(pem_file)
            app.state.evs_state["params"]["pem_file"] = pem_file_path

    _persist_active_session_state(request)
    return templates.TemplateResponse(
        request,
        "partials/pem_upload_status.html",
        {
            "pem_file_path": pem_file_path,
            "pem_upload_error": pem_upload_error,
        },
    )


@app.post("/ui/evs/reset", response_class=HTMLResponse)
async def evs_reset(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
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
    app.state.evs_state = reset_state
    app.state.create_form_values = default_create_values()
    app.state.last_create_operation = None
    app.state.document_uploads = []
    app.state.document_upload_notices = []
    return _render_connect_panel(request)


@app.post("/ui/create/upload-documents", response_class=HTMLResponse)
async def upload_documents_for_create(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)

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
        app.state.document_uploads = saved
    app.state.document_upload_notices = notices

    _persist_active_session_state(request)
    return templates.TemplateResponse(
        request,
        "partials/selected_documents.html",
        {
            "document_uploads": app.state.document_uploads,
            "document_upload_error": upload_error,
            "document_upload_notices": notices,
        },
    )


@app.post("/ui/evs/health", response_class=HTMLResponse)
async def evs_run_health(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    state = app.state.evs_state
    if not state["connected"]:
        _clear_health_result(state)
        state["health_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.health()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request)
    if VSManager is None:
        _clear_health_result(state)
        state["health_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.health()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request)
    health_fn = getattr(VSManager, "health", None)
    if not callable(health_fn):
        _clear_health_result(state)
        state["health_preview"] = "Cannot run: VSManager.health is not callable."
        state["last_error"] = "VSManager.health() is not callable."
        _append_connect_step(state, "VSManager.health()", "error", "VSManager.health is missing or not callable.")
        return _render_connect_panel(request)
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
    return _render_connect_panel(request)


@app.post("/ui/evs/list", response_class=HTMLResponse)
async def evs_run_list(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    state = app.state.evs_state
    _clear_destroy_result(state)
    if not state["connected"]:
        _clear_list_result(state)
        state["list_preview"] = "Connect in Step 1 first."
        state["last_error"] = "Run blocked: connection is not established."
        _append_connect_step(state, "VSManager.list()", "warn", "Blocked: Step 1 is not connected.")
        return _render_connect_panel(request)
    if VSManager is None:
        _clear_list_result(state)
        state["list_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        state["last_error"] = "VS runtime is unavailable."
        _append_connect_step(state, "VSManager.list()", "error", f"Runtime unavailable: {TERADATA_IMPORT_ERROR}")
        return _render_connect_panel(request)
    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        _clear_list_result(state)
        state["list_preview"] = "Cannot run: VSManager.list is not callable."
        state["last_error"] = "VSManager.list() is not callable."
        _append_connect_step(state, "VSManager.list()", "error", "VSManager.list is missing or not callable.")
        return _render_connect_panel(request)
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
    return _render_connect_panel(request)


@app.post("/ui/chat/vs-list", response_class=HTMLResponse)
async def chat_run_list(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)

    state = app.state.evs_state
    if not state["connected"]:
        _clear_chat_list_result(state)
        state["chat_list_preview"] = "Connect in Step 1 first."
        _persist_active_session_state(request)
        return templates.TemplateResponse(
            request,
            "partials/chat_vector_store_list.html",
            {"evs": state, "is_oob": False},
        )

    if VSManager is None:
        _clear_chat_list_result(state)
        state["chat_list_preview"] = f"Cannot run: {TERADATA_IMPORT_ERROR}"
        _persist_active_session_state(request)
        return templates.TemplateResponse(
            request,
            "partials/chat_vector_store_list.html",
            {"evs": state, "is_oob": False},
        )

    list_fn = getattr(VSManager, "list", None)
    if not callable(list_fn):
        _clear_chat_list_result(state)
        state["chat_list_preview"] = "Cannot run: VSManager.list is not callable."
        _persist_active_session_state(request)
        return templates.TemplateResponse(
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

    _persist_active_session_state(request)
    return templates.TemplateResponse(
        request,
        "partials/chat_vector_store_list.html",
        {"evs": state, "is_oob": False},
    )


@app.post("/ui/evs/select", response_class=HTMLResponse)
async def evs_select_from_list(request: Request, vs_name: str = Form(default="")):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)

    state = app.state.evs_state
    selected_name = (vs_name or str(request.query_params.get("vs_name", ""))).strip()
    state["selected_vs_name"] = selected_name
    state["destroy_status"] = "neutral"
    if selected_name:
        state["destroy_preview"] = f"Selected '{selected_name}'. Click Delete to delete."
        _append_connect_step(state, "Vector Store selection", "ok", f"Selected '{selected_name}'.")
    else:
        state["destroy_preview"] = "Click a row in list, then destroy it here."
        _append_connect_step(state, "Vector Store selection", "warn", "Selection payload was empty.")
    return _render_connect_panel(request)


@app.post("/ui/evs/destroy", response_class=HTMLResponse)
async def evs_destroy_selected(request: Request, vs_name: str = Form(default="")):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    return await handle_destroy_selected(
        request,
        app.state.evs_state,
        vs_name,
        vector_store_cls=VectorStore,
        vs_manager=VSManager,
        execute_sql_fn=execute_sql,
        teradata_import_error=TERADATA_IMPORT_ERROR,
        render_connect_panel=_render_connect_panel,
        append_connect_step=_append_connect_step,
    )


@app.post("/ui/create/upload", response_class=HTMLResponse)
async def upload_and_prepare_create(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    is_htmx = request.headers.get("HX-Request", "").lower() == "true"
    response = await handle_upload_and_prepare_create(
        request,
        app,
        templates,
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
    _persist_active_session_state(request)
    return response


@app.post("/ui/chat", response_class=HTMLResponse)
async def chat_send(
    request: Request,
    message: str = Form(...),
    validation_target: str = Form(default="vectorstore.ask"),
    selected_vs_name: str = Form(default=""),
):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    response = await handle_chat_send(
        request,
        app,
        templates,
        message=message,
        validation_target=validation_target,
        selected_vs_name=selected_vs_name,
        build_evs_reply=_build_evs_reply,
    )
    _persist_active_session_state(request)
    return response


@app.post("/ui/chat/reset", response_class=HTMLResponse)
async def chat_reset(request: Request):
    if not _is_logged_in(request):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request)
    response = await handle_chat_reset(request, app, templates)
    _persist_active_session_state(request)
    return response


@app.post("/api/bookrag/retrieve")
async def api_bookrag_retrieve(request: Request, payload: BookRAGRetrieveRequest):
    if not _is_logged_in(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    _activate_session_state(request)

    if VectorStore is None:
        raise HTTPException(status_code=503, detail=f"VectorStore runtime is unavailable: {TERADATA_IMPORT_ERROR}")
    if execute_sql is None:
        raise HTTPException(status_code=503, detail="teradataml.execute_sql is unavailable.")

    question = str(payload.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required.")

    vector_store_name = str(payload.vector_store_name or "").strip()
    if not vector_store_name:
        raise HTTPException(status_code=400, detail="vector_store_name is required.")

    try:
        vector_store = VectorStore(vector_store_name)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"cannot open VectorStore('{vector_store_name}'): {ex}") from ex

    try:
        try:
            similarity_result = vector_store.similarity_search(question=question)
        except TypeError:
            similarity_result = vector_store.similarity_search(question)
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"similarity_search failed on '{vector_store_name}': {ex}") from ex

    try:
        evidence = retrieve_bookrag_evidence(
            vector_store_name=vector_store_name,
            similarity_result=similarity_result,
            execute_sql_fn=execute_sql,
            schema_name=str(payload.schema_name).strip() or None,
        )
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"BookRAG evidence retrieval failed for '{vector_store_name}': {ex}") from ex

    assistant_message = _build_bookrag_chat_reply(evidence, vector_store_name)
    user_time = datetime.now().strftime("%H:%M")
    assistant_time = datetime.now().strftime("%H:%M")
    app.state.chat_history.append({
        "role": "user",
        "content": question,
        "time": user_time,
    })
    app.state.chat_history.append({
        "role": "assistant",
        "content": assistant_message,
        "time": assistant_time,
    })
    app.state.chat_history = app.state.chat_history[-80:]

    return {
        "question": question,
        "vector_store_name": vector_store_name,
        "evidence": evidence,
        "assistant_message": assistant_message,
        "user_time": user_time,
        "assistant_time": assistant_time,
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}

