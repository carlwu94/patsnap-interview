from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db.connection import connect
from app.db.schema import initialize_database


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    artifacts_dir = tmp_path / "artifacts"
    logs_dir = tmp_path / "logs"
    artifacts_dir.mkdir()
    logs_dir.mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "static").mkdir()
    return Settings(
        root_dir=tmp_path,
        data_dir=data_dir,
        pdf_dir=data_dir / "pdf",
        metadata_path=data_dir / "index.xlsx",
        artifacts_dir=artifacts_dir,
        db_path=artifacts_dir / "test.sqlite3",
        logs_dir=logs_dir,
        templates_dir=tmp_path / "templates",
        static_dir=tmp_path / "static",
        llm_base_url=None,
        llm_api_key=None,
        llm_model=None,
        use_ocr_fallback=True,
        parse_activity_log_path=logs_dir / "parse_activity.csv",
        parse_failure_log_path=logs_dir / "parse_failures.csv",
        commit_interval=20,
        progress_interval=20,
    )


@pytest.fixture()
def seeded_connection(test_settings: Settings):
    connection = connect(test_settings.db_path)
    initialize_database(connection)
    connection.executemany(
        """
        INSERT INTO patents (
            patent_id, title, assignee, filing_date, ipc_main, ipc_all,
            abstract, claim_1, claims_text, full_text, source_pdf, parse_status, parse_error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "CNTEST001A",
                "Solid electrolyte battery",
                "CATL",
                "2024-01-06",
                "H01M10/0562",
                "H01M10/0562 | H01M4/13",
                "Solid electrolyte battery abstract",
                "Claim 1",
                "solid electrolyte claim text",
                "solid electrolyte full text",
                "CNTEST001A.pdf",
                "success",
                None,
            ),
            (
                "CNTEST002A",
                "Lithium cathode material",
                "CATL",
                "2025-02-14",
                "H01M4/525",
                "H01M4/525",
                "Lithium cathode abstract",
                "Claim 1",
                "cathode claim text",
                "lithium cathode full text",
                "CNTEST002A.pdf",
                "success",
                None,
            ),
            (
                "CNTEST003A",
                "Battery separator",
                "BYD",
                "2025-03-12",
                "H01M4/525",
                "H01M4/525",
                "Separator abstract",
                "Claim 1",
                "separator claim text",
                "separator full text",
                "CNTEST003A.pdf",
                "success",
                None,
            ),
        ],
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
