from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.security import is_sensitive_key
from app.services.workflow_jobs import (
    BOOKRAG_CSV_GENERATE_JOB,
    BOOKRAG_CSV_LOAD_JOB,
    BOOKRAG_PARSE_JOB,
    MULTI_FORMAT_CSV_GENERATE_JOB,
    MULTI_FORMAT_CSV_LOAD_JOB,
    MULTI_FORMAT_PARSE_JOB,
    VECTOR_STORE_CREATE_JOB,
    WORKFLOW_JOB_LABELS,
)
from app.web_support import (
    _activate_session_state,
    _is_logged_in,
    _persist_active_session_state,
    _session_id_from_request,
)


router = APIRouter()


def _session_principal(request: Request):
    auth_store = getattr(request.app.state, "auth_store", None)
    if auth_store is None:
        return None
    return auth_store.get_session(_session_id_from_request(request))


def _selected_connection_profile_id(request: Request) -> int | None:
    selected = (getattr(request.app.state, "evs_state", {}) or {}).get("selected_connection_id")
    if selected is not None:
        return int(selected)
    auth_store = getattr(request.app.state, "auth_store", None)
    saved = auth_store.get_connection_profile() if auth_store is not None else None
    return int(saved["id"]) if saved and saved.get("id") is not None else None


def split_sensitive_job_payload(payload: dict) -> tuple[dict, dict]:
    public: dict = {}
    secret: dict = {}
    for key, value in payload.items():
        if is_sensitive_key(key):
            if value is not None and value != "":
                secret[key] = value
        elif isinstance(value, dict):
            public_child, secret_child = split_sensitive_job_payload(value)
            public[key] = public_child
            if secret_child:
                secret[key] = secret_child
        elif isinstance(value, list):
            public_items = []
            secret_items = []
            has_secret = False
            for item in value:
                if isinstance(item, dict):
                    public_item, secret_item = split_sensitive_job_payload(item)
                    public_items.append(public_item)
                    secret_items.append(secret_item or None)
                    has_secret = has_secret or bool(secret_item)
                else:
                    public_items.append(item)
                    secret_items.append(None)
            public[key] = public_items
            if has_secret:
                secret[key] = secret_items
        else:
            public[key] = value
    return public, secret


def queue_workflow_job(request: Request, *, kind: str, payload: dict) -> dict:
    repository = getattr(request.app.state, "job_repository", None)
    principal = _session_principal(request)
    if repository is None or principal is None:
        raise RuntimeError("The authenticated persistent job service is unavailable.")
    public_payload, secret_payload = split_sensitive_job_payload(payload)
    return repository.create(
        kind=kind,
        payload=public_payload,
        secret_payload=secret_payload,
        owner_user_id=principal.user_id,
        connection_profile_id=_selected_connection_profile_id(request),
    )


def render_job_progress(request: Request, job: dict):
    return request.app.state.templates.TemplateResponse(
        request,
        "partials/job_progress.html",
        {
            "job": job,
            "job_label": WORKFLOW_JOB_LABELS.get(job.get("kind"), "Background operation"),
        },
    )


def _render_completed_workflow_job(request: Request, job: dict):
    summary = (job.get("result") or {}).get("summary")
    kind = job.get("kind")
    evs = request.app.state.evs_state
    if kind == BOOKRAG_PARSE_JOB:
        template = "partials/bookrag_document_parsing_result.html"
        context = {"bookrag_document_parsing": summary, "bookrag_document_parsing_error": ""}
    elif kind == BOOKRAG_CSV_GENERATE_JOB:
        template = "partials/bookrag_csv_generation_result.html"
        context = {
            "bookrag_csv_generation": summary,
            "bookrag_csv_generation_error": "",
            "bookrag_load_csv_runs": [summary] if summary and summary.get("status") == "ready" else [],
            "bookrag_selected_load_csv_run_id": str(summary.get("csv_run_id") or "") if summary else "",
            "bookrag_load_panel_oob": bool(summary and summary.get("status") == "ready"),
            "evs": evs,
        }
    elif kind == BOOKRAG_CSV_LOAD_JOB:
        template = "partials/bookrag_csv_load_result.html"
        context = {
            "bookrag_csv_load": summary,
            "bookrag_csv_load_error": "",
            "bookrag_loaded_csv_runs": [summary] if summary else [],
            "bookrag_selected_loaded_csv_run_id": str(summary.get("csv_run_id") or "") if summary else "",
            "bookrag_vector_name_oob": bool(summary),
            "create_values": getattr(request.app.state, "create_form_values", {}),
            "evs": evs,
        }
    elif kind == MULTI_FORMAT_PARSE_JOB:
        template = "partials/multi_format_document_parsing_result.html"
        context = {"multi_format_document_parsing": summary, "multi_format_document_parsing_error": ""}
    elif kind == MULTI_FORMAT_CSV_GENERATE_JOB:
        template = "partials/multi_format_csv_generation_result.html"
        context = {
            "multi_format_csv_generation": summary,
            "multi_format_csv_generation_error": "",
            "multi_format_load_csv_runs": [summary] if summary and summary.get("status") == "ready" else [],
            "multi_format_selected_load_csv_run_id": str(summary.get("csv_run_id") or "") if summary else "",
            "multi_format_load_panel_oob": bool(summary and summary.get("status") == "ready"),
            "evs": evs,
        }
    elif kind == MULTI_FORMAT_CSV_LOAD_JOB:
        template = "partials/multi_format_csv_load_result.html"
        context = {
            "multi_format_csv_load": summary,
            "multi_format_csv_load_error": "",
            "multi_format_loaded_csv_runs": [summary] if summary else [],
            "multi_format_selected_loaded_csv_run_id": str(summary.get("csv_run_id") or "") if summary else "",
            "multi_format_vector_name_oob": bool(summary),
            "create_values": getattr(request.app.state, "create_form_values", {}),
            "evs": evs,
        }
    elif kind == VECTOR_STORE_CREATE_JOB:
        create_result = (job.get("result") or {}).get("create_result") or {}
        request.app.state.last_create_operation = create_result
        status = str(create_result.get("status") or "error")
        message = str(create_result.get("message") or "Vector Store creation finished.")
        if status == "error":
            evs["last_success"] = ""
            evs["last_notice"] = ""
            evs["last_error"] = message
        elif status == "pending":
            evs["last_success"] = ""
            evs["last_error"] = ""
            evs["last_notice"] = message
        else:
            evs["last_error"] = ""
            evs["last_notice"] = ""
            evs["last_success"] = message
            evs["last_created_vs_name"] = str(create_result.get("vector_store_name") or "")
        _persist_active_session_state(request, request.app)
        template = "partials/create_result.html"
        context = {"create_result": create_result, "evs": evs, "is_htmx": True}
    else:
        return render_job_progress(request, job)
    return request.app.state.templates.TemplateResponse(request, template, context)


def _authorized_job(request: Request, job_id: str) -> tuple[dict | None, object | None]:
    principal = _session_principal(request)
    repository = getattr(request.app.state, "job_repository", None)
    if principal is None or repository is None:
        return None, principal
    job = repository.get(job_id)
    if job is None:
        return None, principal
    if job.get("owner_user_id") != principal.user_id and principal.role != "admin":
        return None, principal
    return job, principal


@router.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
async def workflow_job_status(request: Request, job_id: str):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    job, principal = _authorized_job(request, job_id)
    if principal is None:
        return HTMLResponse("Unauthorized", status_code=401)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    if job.get("status") == "succeeded":
        return _render_completed_workflow_job(request, job)
    return render_job_progress(request, job)


@router.post("/ui/jobs/{job_id}/cancel", response_class=HTMLResponse)
async def cancel_workflow_job(request: Request, job_id: str):
    if not _is_logged_in(request, request.app):
        return HTMLResponse("Unauthorized", status_code=401)
    _activate_session_state(request, request.app)
    job, principal = _authorized_job(request, job_id)
    if principal is None:
        return HTMLResponse("Unauthorized", status_code=401)
    if job is None:
        return HTMLResponse("Job not found", status_code=404)
    owner_filter = None if principal.role == "admin" else principal.user_id
    request.app.state.job_repository.cancel(job_id, owner_user_id=owner_filter)
    return render_job_progress(request, request.app.state.job_repository.get(job_id) or job)
