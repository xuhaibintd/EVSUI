from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = PROJECT_DIR / "uploads"
DOCUMENT_UPLOAD_DIR = UPLOAD_DIR / "documents"
DEBUG_UPLOAD_DIR = UPLOAD_DIR / "multi_format_stage"
PEM_UPLOAD_DIR = UPLOAD_DIR / "pem"
VS_BASICS_DIR = PROJECT_DIR.parent / "VS_Basics_Full_Kit"
AUTH_USERS_FILE_DEFAULT = BASE_DIR / "config" / "auth_users.json"
SESSION_COOKIE_NAME = "evsui_sid"
DEFAULT_PAT_TOKEN = ""
DEFAULT_EVSUI_API_TOKEN = "evsui-dev-token"
DEFAULT_CHAT_VS_NAME = "TokioMarine_test"
DEFAULT_LOGIN_USERNAME = ""
DEFAULT_LOGIN_PASSWORD = ""

for _path in (UPLOAD_DIR, DOCUMENT_UPLOAD_DIR, DEBUG_UPLOAD_DIR, PEM_UPLOAD_DIR):
    _path.mkdir(parents=True, exist_ok=True)
