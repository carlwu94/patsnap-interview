from __future__ import annotations

import pandas as pd

from app.config import get_settings
from app.db.ingest import PdfExtractionResult, build_patent_record, load_metadata


def test_load_metadata_maps_expected_columns():
    settings = get_settings()
    dataframe = load_metadata(settings.metadata_path)
    assert "patent_id" in dataframe.columns
    assert "assignee" in dataframe.columns
    assert "source_pdf" in dataframe.columns
    assert dataframe.iloc[0]["patent_id"]


def test_build_patent_record_marks_success_ocr(monkeypatch, test_settings):
    pdf_dir = test_settings.pdf_dir
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / "CNTESTOCR.pdf").write_bytes(b"placeholder")

    row = pd.Series(
        {
            "patent_id": "CNTESTOCR",
            "title_translated": "OCR patent",
            "assignee": "OCR Corp",
            "filing_date": "2024-01-01",
            "source_pdf": "CNTESTOCR.pdf",
        }
    )

    monkeypatch.setattr(
        "app.db.ingest.extract_pdf_text",
        lambda _path: PdfExtractionResult(text="ocr recovered text", used_ocr=True),
    )

    record = build_patent_record(test_settings, row)
    assert record.parse_status == "success_ocr"
    assert record.full_text == "ocr recovered text"
