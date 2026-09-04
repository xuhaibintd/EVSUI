from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.runtime import SESSION_COOKIE_NAME
from app.web_support import (
    _apply_saved_connection_config,
    _is_logged_in,
    _is_poc_auth_configured,
    _new_session_scope,
    _session_id_from_request,
)


router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_logged_in(request, request.app):
        return RedirectResponse(url="/", status_code=303)
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {"error": "", "logged_in": False, "username": "", "password": ""},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(default=""), password: str = Form(default="")):
    clean_username = username.strip()
    principal = request.app.state.auth_store.authenticate(clean_username, password)
    if principal is not None:
        sid = request.app.state.auth_store.create_session(principal)
        scope = _new_session_scope(username=principal.username)
        scope["role"] = principal.role
        _apply_saved_connection_config(scope, request.app, principal)
        request.app.state.user_sessions[sid] = scope
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            sid,
            max_age=request.app.state.auth_store.session_ttl_seconds,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return response
    error_message = "Invalid username or password."
    if not _is_poc_auth_configured(request.app):
        error_message = (
            "Server auth is not configured. Set EVSUI_BOOTSTRAP_ADMIN and "
            "EVSUI_BOOTSTRAP_PASSWORD, then restart EVSUI."
        )
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error_message,
            "logged_in": False,
            "username": clean_username,
            "password": "",
        },
    )


@router.post("/logout")
async def logout(request: Request):
    sid = _session_id_from_request(request)
    if sid:
        request.app.state.auth_store.revoke_session(sid)
        request.app.state.user_sessions.pop(sid, None)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
