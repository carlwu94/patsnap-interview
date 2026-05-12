from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.web.routes.api import router as api_router
from app.web.routes.pages import router as pages_router


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(title="Patent QA Platform", version="0.1.0")
    application.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
    application.include_router(pages_router)
    application.include_router(api_router)
    return application


app = create_app()
