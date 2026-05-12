from __future__ import annotations

import json
from typing import Any
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.chat_service import chat_with_agent, stream_chat_with_agent
from app.config import SUPPORTED_LLM_MODELS, get_settings, with_llm_model
from app.db.connection import connect
from app.services.patent_query import (
    get_assignee_trend,
    get_patent_by_id,
    get_top_ipc,
    search_by_keyword,
)


router = APIRouter(prefix="/api", tags=["api"])


class SearchRequest(BaseModel):
    keyword: str
    assignee: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    limit: int = Field(default=20, ge=1, le=100)


class TrendRequest(BaseModel):
    assignee: str
    start_year: int
    end_year: int


class ChatRequest(BaseModel):
    history: list["ChatHistoryMessage"] = Field(default_factory=list)
    message: str
    model: str | None = None


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


def _resolve_chat_settings(model: str | None):
    try:
        return with_llm_model(get_settings(), model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/search")
def search(request: SearchRequest) -> list[dict[str, Any]]:
    settings = get_settings()
    connection = connect(settings.db_path)
    try:
        return search_by_keyword(connection=connection, **request.model_dump())
    finally:
        connection.close()


@router.get("/patents/{patent_id}")
def patent_details(patent_id: str) -> dict[str, Any]:
    settings = get_settings()
    connection = connect(settings.db_path)
    try:
        result = get_patent_by_id(connection, patent_id)
    finally:
        connection.close()
    if result is None:
        raise HTTPException(status_code=404, detail="Patent not found")
    return result


@router.post("/trend")
def trend(request: TrendRequest) -> list[dict[str, Any]]:
    settings = get_settings()
    connection = connect(settings.db_path)
    try:
        return get_assignee_trend(connection=connection, **request.model_dump())
    finally:
        connection.close()


@router.get("/ipc/top")
def top_ipc(top_n: int = 10) -> list[dict[str, Any]]:
    settings = get_settings()
    connection = connect(settings.db_path)
    try:
        return get_top_ipc(connection=connection, top_n=top_n)
    finally:
        connection.close()


@router.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    history = [item.model_dump() for item in request.history]
    return chat_with_agent(_resolve_chat_settings(request.model), request.message, history=history)


@router.post("/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    settings = _resolve_chat_settings(request.model)
    history = [item.model_dump() for item in request.history]

    def event_stream() -> Any:
        for event in stream_chat_with_agent(settings, request.message, history=history):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
