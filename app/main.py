from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.errors import configure_error_handlers
from app.core.runtime_manager import RuntimeIsolationMiddleware
from app.core.security import SecurityMiddleware
from app.core.settings import Settings
from app.runtime import STATIC_DIR, TEMPLATES_DIR
from app.routers.api import router as api_router
from app.routers.web import router as web_router
from app.web_support import initialize_app_state


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_settings.validate_runtime()
    application = FastAPI(title="Teradata Vector Store", version="0.6.0")
    application.state.settings = resolved_settings
    configure_error_handlers(application)
    application.add_middleware(SecurityMiddleware)
    application.add_middleware(RuntimeIsolationMiddleware)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    initialize_app_state(
        application,
        Jinja2Templates(directory=str(TEMPLATES_DIR)),
        settings=resolved_settings,
    )
    application.include_router(web_router)
    application.include_router(api_router)
    return application


app = create_app()
