from __future__ import annotations

import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from fastapi import Request


def load_connect_defaults(
    latest_uploaded_pem_relative: Callable[[], str],
    vs_basics_dir: Path,
    default_pat_token: str,
) -> dict[str, str]:
    _ = vs_basics_dir
    preferred_pem = "uploads\\pem\\<redacted-user>__jcb.pem"
    pem_path = preferred_pem
    try:
        if not Path(preferred_pem).exists():
            pem_path = latest_uploaded_pem_relative() or preferred_pem
    except Exception:
        pem_path = preferred_pem
    return {
        "host": "<redacted-host>",
        "username": "<redacted-user>",
        "password": "<redacted-user>",
        "ues_url": "https://tddemos.innovationlabs.teradata.com/api/accounts/1ca5520e-5abd-441d-ba25-40c83ff23b2e/open-analytics",
        "pat_token": default_pat_token,
        "pem_file": pem_path,
    }


def default_evs_state(load_defaults: Callable[[], dict[str, str]]) -> dict[str, Any]:
    connect_defaults = load_defaults()
    return {
        "connected": False,
        "connected_at": "",
        "last_error": "",
        "last_success": "",
        "health_preview": "",
        "health_columns": [],
        "health_rows": [],
        "health_row_count": 0,
        "list_preview": "",
        "list_columns": [],
        "list_rows": [],
        "list_row_count": 0,
        "chat_vs_options": [],
        "chat_list_preview": "",
        "chat_list_loaded_by_user": False,
        "list_loaded_by_user": False,
        "selected_vs_name": "",
        "last_created_vs_name": "",
        "destroy_preview": "",
        "destroy_status": "neutral",
        "actual_params": {},
        "connect_steps": [],
        "params": connect_defaults,
    }


def new_session_scope(username: str, default_evs_state_fn: Callable[[], dict], default_create_values_fn: Callable[[], dict]) -> dict:
    return {
        "username": username.strip(),
        "evs_state": default_evs_state_fn(),
        "create_form_values": default_create_values_fn(),
        "last_create_operation": None,
        "document_uploads": [],
        "document_upload_notices": [],
        "chat_history": [],
    }


def session_id_from_request(request: Request, session_cookie_name: str) -> str:
    return str(request.cookies.get(session_cookie_name, "")).strip()


def current_user(request: Request) -> str:
    return request.cookies.get("evsui_user", "")


def activate_session_state(
    request: Request,
    app,
    session_cookie_name: str,
    default_evs_state_fn: Callable[[], dict],
    default_create_values_fn: Callable[[], dict],
) -> dict:
    sid = session_id_from_request(request, session_cookie_name)
    sessions = app.state.user_sessions
    scope = sessions.get(sid)
    if scope is None:
        scope = new_session_scope(
            username=current_user(request),
            default_evs_state_fn=default_evs_state_fn,
            default_create_values_fn=default_create_values_fn,
        )
        if sid:
            sessions[sid] = scope

    app.state.evs_state = scope["evs_state"]
    app.state.create_form_values = scope["create_form_values"]
    app.state.last_create_operation = scope["last_create_operation"]
    app.state.document_uploads = scope["document_uploads"]
    app.state.document_upload_notices = scope["document_upload_notices"]
    app.state.chat_history = scope["chat_history"]
    return scope


def persist_active_session_state(request: Request, app, session_cookie_name: str) -> None:
    sid = session_id_from_request(request, session_cookie_name)
    if not sid:
        return
    scope = app.state.user_sessions.get(sid)
    if scope is None:
        return
    scope["evs_state"] = app.state.evs_state
    scope["create_form_values"] = app.state.create_form_values
    scope["last_create_operation"] = app.state.last_create_operation
    scope["document_uploads"] = app.state.document_uploads
    scope["document_upload_notices"] = app.state.document_upload_notices
    scope["chat_history"] = app.state.chat_history


def auth_users_file_path(auth_users_file_default: Path) -> Path:
    raw = str(os.getenv("POC_AUTH_FILE", str(auth_users_file_default))).strip()
    return Path(raw).expanduser()


def load_auth_users(auth_users_file_default: Path, logger: logging.Logger) -> dict[str, str]:
    users: dict[str, str] = {}
    path = auth_users_file_path(auth_users_file_default)
    if path.exists() and path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_users = payload.get("users", payload) if isinstance(payload, dict) else payload
            if isinstance(raw_users, dict):
                for raw_name, raw_password in raw_users.items():
                    name = str(raw_name).strip()
                    if not name:
                        continue
                    users[name] = str(raw_password)
            elif isinstance(raw_users, list):
                for item in raw_users:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("username", "")).strip()
                    if not name:
                        continue
                    users[name] = str(item.get("password", ""))
        except Exception as ex:
            logger.warning("Failed to parse auth users file '%s': %s", path, ex)
    return users


def user_initials(username: str) -> str:
    value = username.strip().upper()
    if not value:
        return "??"
    parts = value.split()
    if len(parts) >= 2:
        return (parts[0][:1] + parts[1][:1])[:2]
    return value[:2]


def is_logged_in(request: Request, app, session_cookie_name: str) -> bool:
    if request.cookies.get("evsui_auth") != "1":
        return False
    sid = session_id_from_request(request, session_cookie_name)
    if not sid:
        return False
    return sid in app.state.user_sessions


def poc_admin_credentials() -> tuple[str, str]:
    username = str(os.getenv("POC_ADMIN_USER", "")).strip()
    password = str(os.getenv("POC_ADMIN_PASSWORD", ""))
    return username, password


def is_poc_auth_configured(load_auth_users_fn: Callable[[], dict[str, str]]) -> bool:
    if load_auth_users_fn():
        return True
    username, password = poc_admin_credentials()
    return bool(username and password)


def is_valid_poc_login(username: str, password: str, load_auth_users_fn: Callable[[], dict[str, str]]) -> bool:
    auth_users = load_auth_users_fn()
    if not auth_users:
        expected_username, expected_password = poc_admin_credentials()
        if expected_username and expected_password:
            auth_users = {expected_username: expected_password}
    if not auth_users:
        return False
    stored_password = auth_users.get(username)
    if stored_password is None:
        return False
    return hmac.compare_digest(password, stored_password)
