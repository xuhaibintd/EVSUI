from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
LOCAL_CONFIG_FILE_DEFAULT = BASE_DIR / "config" / "local_dev.json"


def _local_config_file() -> Path:
    raw = str(os.getenv("EVSUI_LOCAL_CONFIG", str(LOCAL_CONFIG_FILE_DEFAULT))).strip()
    return Path(raw).expanduser()


def load_local_config() -> dict[str, Any]:
    path = _local_config_file()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as ex:
        raise RuntimeError(f"Invalid local config at {path}: {ex}") from ex
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid local config at {path}: must be a JSON object")
    return payload


def _section(name: str) -> dict[str, Any]:
    payload = load_local_config()
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def _string_value(section: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = section.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def local_login_defaults() -> tuple[str, str]:
    login = _section("login")
    return (
        _string_value(login, "username", "user"),
        _string_value(login, "password"),
    )


def local_auth_users() -> dict[str, str]:
    login = _section("login")
    users: dict[str, str] = {}
    raw_users = login.get("users")
    if isinstance(raw_users, dict):
        for raw_name, raw_password in raw_users.items():
            name = str(raw_name).strip()
            if name:
                users[name] = str(raw_password)
    elif isinstance(raw_users, list):
        for item in raw_users:
            if not isinstance(item, dict):
                continue
            name = str(item.get("username", "")).strip()
            if name:
                users[name] = str(item.get("password", ""))

    default_username, default_password = local_login_defaults()
    if default_username and default_password and default_username not in users:
        users[default_username] = default_password
    return users


def local_connection_defaults() -> dict[str, str]:
    connection = _section("connection")
    return {
        "host": _string_value(connection, "host"),
        "username": _string_value(connection, "username", "user"),
        "password": _string_value(connection, "password"),
        "ues_url": _string_value(connection, "ues_url", "UES_URL"),
        "pat_token": _string_value(connection, "pat_token", "PAT_TOKEN"),
        "pem_file": _string_value(connection, "pem_file", "pem_path"),
    }


def local_unstructured_defaults() -> dict[str, Any]:
    unstructured = _section("unstructured")
    return dict(unstructured)
