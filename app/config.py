from __future__ import annotations

import os
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
import tomllib


SUPPORTED_LLM_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    pdf_dir: Path
    metadata_path: Path
    artifacts_dir: Path
    db_path: Path
    logs_dir: Path
    templates_dir: Path
    static_dir: Path
    llm_base_url: str | None
    llm_api_key: str | None
    llm_model: str | None
    use_ocr_fallback: bool
    parse_activity_log_path: Path
    parse_failure_log_path: Path
    commit_interval: int
    progress_interval: int


def with_llm_model(settings: Settings, llm_model: str | None) -> Settings:
    if not llm_model:
        return settings
    if llm_model not in SUPPORTED_LLM_MODELS:
        raise ValueError(f"Unsupported model: {llm_model}")
    return replace(settings, llm_model=llm_model)


def load_app_config(root_dir: Path) -> dict:
    config_path = root_dir / "appsettings.toml"
    if not config_path.exists():
        return {}

    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def get_settings() -> Settings:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = root_dir / "target" / "笔试数据包" / "20260510125342232"
    artifacts_dir = root_dir / "artifacts"
    logs_dir = root_dir / "logs"
    config = load_app_config(root_dir)
    llm_config = config.get("llm", {})
    ingestion_config = config.get("ingestion", {})

    return Settings(
        root_dir=root_dir,
        data_dir=data_dir,
        pdf_dir=data_dir / "pdf",
        metadata_path=data_dir / "index.xlsx",
        artifacts_dir=artifacts_dir,
        db_path=artifacts_dir / "patents.sqlite3",
        logs_dir=logs_dir,
        templates_dir=root_dir / "templates",
        static_dir=root_dir / "static",
        llm_base_url=os.getenv("DEEPSEEK_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or llm_config.get("base_url") or "https://api.deepseek.com/v1",
        llm_api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or llm_config.get("api_key"),
        llm_model=os.getenv("DEEPSEEK_MODEL") or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or llm_config.get("model") or "deepseek-v4",
        use_ocr_fallback=bool(ingestion_config.get("use_ocr_fallback", True)),
        parse_activity_log_path=logs_dir / str(ingestion_config.get("activity_log_filename", "parse_activity.csv")),
        parse_failure_log_path=logs_dir / str(ingestion_config.get("failure_log_filename", "parse_failures.csv")),
        commit_interval=max(1, int(ingestion_config.get("commit_interval", 20))),
        progress_interval=max(1, int(ingestion_config.get("progress_interval", 20))),
    )
