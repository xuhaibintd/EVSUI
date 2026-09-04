from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.security import redact_sensitive_text
from app.runtime import SESSION_COOKIE_NAME
from app.web_support import (
    _activate_session_state,
    _persist_active_session_state,
    _session_id_from_request,
)


router = APIRouter()


def _admin_principal(request: Request):
    principal = request.app.state.auth_store.get_session(_session_id_from_request(request))
    if principal is None or principal.role != "admin":
        return None
    return principal


def _render_user_admin(
    request: Request,
    *,
    status: dict[str, str] | None = None,
    status_code: int = 200,
    active_tab: str = "connection",
    selected_connection_id: int | None = None,
    new_connection: bool = False,
):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    _activate_session_state(request, request.app)
    connection_profiles = []
    try:
        connection_profiles = request.app.state.auth_store.list_connection_profiles()
        connection_config = (
            {}
            if new_connection
            else request.app.state.auth_store.get_connection_profile(selected_connection_id) or {}
        )
    except Exception as ex:
        connection_config = {}
        if status is None:
            status = {
                "kind": "error",
                "detail": f"System connection configuration could not be loaded: {redact_sensitive_text(ex)}",
            }
            status_code = 500
    return request.app.state.templates.TemplateResponse(
        request,
        "user_admin.html",
        {
            "logged_in": True,
            "username": principal.username,
            "user_role": principal.role,
            "evs": request.app.state.evs_state,
            "users": request.app.state.auth_store.list_users(),
            "roles": ("admin", "operator", "viewer"),
            "connection_config": connection_config,
            "connection_profiles": connection_profiles,
            "connection_password_configured": bool(connection_config.get("password")),
            "connection_pat_configured": bool(connection_config.get("pat_token")),
            "unstructured_api_key_configured": bool(
                (request.app.state.evs_state.get("params") or {}).get("unstructured_api_key")
            ),
            "status": status,
            "active_tab": active_tab if active_tab in {"connection", "unstructured", "users"} else "connection",
        },
        status_code=status_code,
    )


def _error_response(request: Request, ex: Exception, *, tab: str, status_code: int = 400, **kwargs):
    return _render_user_admin(
        request,
        status={"kind": "error", "detail": redact_sensitive_text(ex)},
        status_code=status_code,
        active_tab=tab,
        **kwargs,
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def user_admin_page(
    request: Request,
    connection_id: int | None = None,
    new_connection: bool = False,
):
    return _render_user_admin(
        request,
        selected_connection_id=connection_id,
        new_connection=new_connection,
    )


@router.post("/admin/connection", response_class=HTMLResponse)
async def system_connection_config_save(
    request: Request,
    connection_id: int | None = Form(default=None),
    connection_name: str = Form(default=""),
    is_default: str = Form(default="false"),
    host: str = Form(default=""),
    username: str = Form(default=""),
    password: str = Form(default=""),
    ues_url: str = Form(default=""),
    pat_token: str = Form(default=""),
    pem_file: UploadFile = File(default=None),
):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        existing = request.app.state.auth_store.get_connection_profile(connection_id) or {}
        pem_payload = None
        pem_filename = str(existing.get("pem_filename") or "").strip()
        if pem_file is not None and pem_file.filename:
            suffix = Path(pem_file.filename).suffix.lower()
            if suffix not in {".pem", ".key", ".crt"}:
                raise ValueError("Only .pem, .key, and .crt files are allowed.")
            pem_payload = await pem_file.read()
            pem_filename = Path(pem_file.filename).name
        values = {
            "name": connection_name.strip(),
            "host": host.strip(),
            "username": username.strip(),
            "password": password or existing.get("password", ""),
            "ues_url": ues_url.strip(),
            "pat_token": (pat_token or "").strip() or existing.get("pat_token", ""),
            "pem_file": "" if existing.get("pem_in_database") else str(existing.get("pem_file") or ""),
            "pem_filename": pem_filename,
            "pem_content": pem_payload,
            "is_default": is_default.strip().lower() in {"1", "true", "yes", "on"},
        }
        missing = [key for key in ("host", "username", "password", "ues_url", "pat_token") if not values[key]]
        if pem_payload is None and not existing.get("pem_in_database"):
            missing.append("pem_file")
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")
        saved = request.app.state.auth_store.save_connection_profile(
            principal.user_id,
            values,
            profile_id=connection_id,
        )
        for scope in request.app.state.user_sessions.values():
            evs_state = scope.get("evs_state", {})
            if not evs_state.get("connected") and (
                evs_state.get("selected_connection_id") == saved.get("id")
                or (saved.get("is_default") and not evs_state.get("selected_connection_id"))
            ):
                evs_state.setdefault("params", {}).update(saved)
                evs_state["selected_connection_id"] = saved.get("id")
                evs_state["selected_connection_name"] = saved.get("name", "")
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"Connection '{saved.get('name', '')}' saved."},
            active_tab="connection",
            selected_connection_id=saved.get("id"),
        )
    except Exception as ex:
        return _error_response(
            request,
            ex,
            tab="connection",
            selected_connection_id=connection_id,
            new_connection=connection_id is None,
        )


@router.post("/admin/connections/{connection_id}/delete", response_class=HTMLResponse)
async def system_connection_config_delete(request: Request, connection_id: int):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        existing = request.app.state.auth_store.get_connection_profile(connection_id)
        request.app.state.auth_store.delete_connection_profile(principal.user_id, connection_id)
        for scope in request.app.state.user_sessions.values():
            state = scope.get("evs_state", {})
            if not state.get("connected") and state.get("selected_connection_id") == connection_id:
                replacement = request.app.state.auth_store.get_connection_profile()
                state["selected_connection_id"] = replacement.get("id") if replacement else None
                state["selected_connection_name"] = replacement.get("name", "") if replacement else ""
                state["params"] = dict(replacement or {})
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"Connection '{(existing or {}).get('name', '')}' deleted."},
            active_tab="connection",
        )
    except Exception as ex:
        return _error_response(
            request,
            ex,
            tab="connection",
            selected_connection_id=connection_id,
        )


@router.post("/admin/unstructured-config", response_class=HTMLResponse)
async def system_unstructured_config_save(
    request: Request,
    unstructured_api_url: str = Form(default=""),
    unstructured_api_key: str = Form(default=""),
    clear_unstructured_api_key: str = Form(default=""),
):
    if _admin_principal(request) is None:
        return HTMLResponse("Forbidden", status_code=403)
    _activate_session_state(request, request.app)
    state = request.app.state.evs_state
    params = state.setdefault("params", {})
    params["unstructured_api_url"] = unstructured_api_url.strip()
    replacement_key = (unstructured_api_key or "").strip()
    if clear_unstructured_api_key.strip().lower() in {"1", "true", "on", "yes"}:
        params["unstructured_api_key"] = ""
    elif replacement_key:
        params["unstructured_api_key"] = replacement_key
    _persist_active_session_state(request, request.app)
    return _render_user_admin(
        request,
        status={"kind": "ok", "detail": "Unstructured IO configuration saved for the current session."},
        active_tab="unstructured",
    )


@router.post("/admin/users/create", response_class=HTMLResponse)
async def user_admin_create(
    request: Request,
    username: str = Form(default=""),
    display_name: str = Form(default=""),
    password: str = Form(default=""),
    role: str = Form(default="viewer"),
):
    if _admin_principal(request) is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        request.app.state.auth_store.create_user(
            username=username,
            display_name=display_name,
            password=password,
            role=role,
        )
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"User '{username.strip()}' created."},
            active_tab="users",
        )
    except Exception as ex:
        return _error_response(request, ex, tab="users")


@router.post("/admin/users/{username}/toggle", response_class=HTMLResponse)
async def user_admin_toggle(request: Request, username: str, enabled: str = Form(default="false")):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        next_enabled = enabled.strip().lower() in {"1", "true", "yes", "on"}
        request.app.state.auth_store.set_enabled(username, next_enabled)
        if not next_enabled and username.lower() == principal.username.lower():
            request.app.state.user_sessions.pop(_session_id_from_request(request), None)
            response = RedirectResponse(url="/login", status_code=303)
            response.delete_cookie(SESSION_COOKIE_NAME)
            return response
        action = "enabled" if next_enabled else "disabled"
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"User '{username}' {action}."},
            active_tab="users",
        )
    except Exception as ex:
        return _error_response(request, ex, tab="users")


@router.post("/admin/users/{username}/password", response_class=HTMLResponse)
async def user_admin_password(request: Request, username: str, password: str = Form(default="")):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        request.app.state.auth_store.reset_password(username, password)
        request.app.state.user_sessions = {
            sid: scope
            for sid, scope in request.app.state.user_sessions.items()
            if str(scope.get("username") or "").lower() != username.lower()
        }
        if username.lower() == principal.username.lower():
            response = RedirectResponse(url="/login", status_code=303)
            response.delete_cookie(SESSION_COOKIE_NAME)
            return response
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"Password for '{username}' reset; existing sessions revoked."},
            active_tab="users",
        )
    except Exception as ex:
        return _error_response(request, ex, tab="users")


@router.post("/admin/users/{username}/role", response_class=HTMLResponse)
async def user_admin_role(request: Request, username: str, role: str = Form(default="viewer")):
    principal = _admin_principal(request)
    if principal is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        request.app.state.auth_store.set_role(username, role)
        if username.lower() == principal.username.lower() and role != "admin":
            return RedirectResponse(url="/", status_code=303)
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"Role for '{username}' changed to '{role}'."},
            active_tab="users",
        )
    except Exception as ex:
        return _error_response(request, ex, tab="users")


@router.get("/admin/users/export")
async def user_admin_export(request: Request):
    if _admin_principal(request) is None:
        return HTMLResponse("Forbidden", status_code=403)
    payload = request.app.state.auth_store.export_users()
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="evsui-users.json"'},
    )


@router.post("/admin/users/import", response_class=HTMLResponse)
async def user_admin_import(request: Request, users_file: UploadFile = File(...)):
    if _admin_principal(request) is None:
        return HTMLResponse("Forbidden", status_code=403)
    try:
        raw = await users_file.read()
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("User import file exceeds 2 MiB.")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("User import file must contain a JSON object.")
        imported = request.app.state.auth_store.import_users(payload)
        return _render_user_admin(
            request,
            status={"kind": "ok", "detail": f"Imported {imported} user(s)."},
            active_tab="users",
        )
    except Exception as ex:
        return _error_response(request, ex, tab="users")
