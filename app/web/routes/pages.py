from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import SUPPORTED_LLM_MODELS, get_settings


settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))
router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    current_settings = get_settings()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_title": "锂离子电池专利问答平台",
            "model_configured": bool(current_settings.llm_api_key and current_settings.llm_model),
            "model_name": current_settings.llm_model,
            "supported_models": SUPPORTED_LLM_MODELS,
        },
    )
