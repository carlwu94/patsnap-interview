from __future__ import annotations

from openai import OpenAI

from app.config import Settings


def build_llm_client(settings: Settings) -> OpenAI | None:
    if not settings.llm_api_key or not settings.llm_model:
        return None

    client_kwargs: dict[str, str] = {"api_key": settings.llm_api_key}
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    return OpenAI(**client_kwargs)
