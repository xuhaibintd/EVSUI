from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.runtime import STATIC_DIR, TEMPLATES_DIR
from app.routers.api import router as api_router
from app.routers.web import router as web_router
from app.web_support import initialize_app_state


app = FastAPI(title="Teradata Vector Store", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
initialize_app_state(app, Jinja2Templates(directory=str(TEMPLATES_DIR)))
app.include_router(web_router)
app.include_router(api_router)
