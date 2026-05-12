from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import fitz
import pandas as pd
import sqlite3
from rapidocr_onnxruntime import RapidOCR

from app.config import Settings
from app.db.connection import connect
from app.db.schema import initialize_database


METADATA_COLUMN_MAP = {
    "公开(公告)号": "patent_id",
    "标题": "title_original",
    "标题(译)(简体中文)": "title_translated",
    "[标]当前申请(专利权)人": "assignee",
    "申请日": "filing_date",
    "摘要": "abstract_original",
    "摘要(译)(简体中文)": "abstract_translated",
    "第一权利要求": "claim_1",
    "权利要求": "claims_text",
    "IPC分类号": "ipc_all",
    "IPC主分类号": "ipc_main",
    "文档链接": "source_pdf",
}

UPSERT_SQL = """
INSERT INTO patents (
    patent_id,
    title,
    assignee,
    filing_date,
    ipc_main,
    ipc_all,
    abstract,
    claim_1,
    claims_text,
    full_text,
    source_pdf,
    parse_status,
    parse_error,
    updated_at
) VALUES (
    :patent_id,
    :title,
    :assignee,
    :filing_date,
    :ipc_main,
    :ipc_all,
    :abstract,
    :claim_1,
    :claims_text,
    :full_text,
    :source_pdf,
    :parse_status,
    :parse_error,
    CURRENT_TIMESTAMP
)
ON CONFLICT(patent_id) DO UPDATE SET
    title = excluded.title,
    assignee = excluded.assignee,
    filing_date = excluded.filing_date,
    ipc_main = excluded.ipc_main,
    ipc_all = excluded.ipc_all,
    abstract = excluded.abstract,
    claim_1 = excluded.claim_1,
    claims_text = excluded.claims_text,
    full_text = excluded.full_text,
    source_pdf = excluded.source_pdf,
    parse_status = excluded.parse_status,
    parse_error = excluded.parse_error,
    updated_at = CURRENT_TIMESTAMP
"""


@dataclass(frozen=True)
class PatentRecord:
    patent_id: str
    title: str
    assignee: str | None
    filing_date: str | None
    ipc_main: str | None
    ipc_all: str | None
    abstract: str | None
    claim_1: str | None
    claims_text: str | None
    full_text: str
    source_pdf: str | None
    parse_status: str
    parse_error: str | None


@dataclass(frozen=True)
class IngestStats:
    total_rows: int
    imported_rows: int
    parsed_pdfs: int
    failed_pdfs: int


@dataclass(frozen=True)
class PdfExtractionResult:
    text: str
    used_ocr: bool


@dataclass(frozen=True)
class ActivityLogEntry:
    timestamp_utc: str
    row_index: int
    total_rows: int
    patent_id: str
    source_pdf: str
    parse_status: str
    parse_error: str
    used_ocr: bool
    text_length: int


class ActivityLogger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = log_path.open("w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(
            self.handle,
            fieldnames=[
                "timestamp_utc",
                "row_index",
                "total_rows",
                "patent_id",
                "source_pdf",
                "parse_status",
                "parse_error",
                "used_ocr",
                "text_length",
            ],
        )
        self.writer.writeheader()
        self.handle.flush()

    def write(self, entry: ActivityLogEntry) -> None:
        self.writer.writerow(asdict(entry))
        self.handle.flush()

    def close(self) -> None:
        self.handle.close()


def load_metadata(metadata_path: Path) -> pd.DataFrame:
    dataframe = pd.read_excel(metadata_path)
    renamed_columns = {
        column: METADATA_COLUMN_MAP.get(str(column).strip(), str(column).strip())
        for column in dataframe.columns
    }
    dataframe = dataframe.rename(columns=renamed_columns)
    return dataframe


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text == "-":
        return None
    return text


@lru_cache(maxsize=1)
def get_ocr_engine() -> RapidOCR:
    return RapidOCR()


def extract_ocr_lines(image_bytes: bytes) -> str:
    ocr_result, _ = get_ocr_engine()(image_bytes)
    if not ocr_result:
        return ""
    return "\n".join(item[1].strip() for item in ocr_result if len(item) > 1 and str(item[1]).strip())


def extract_pdf_text(pdf_path: Path, use_ocr_fallback: bool) -> PdfExtractionResult:
    parts: list[str] = []
    used_ocr = False
    with fitz.open(pdf_path) as document:
        for page in document:
            page_text = page.get_text("text").strip()
            if page_text:
                parts.append(page_text)
                continue

            if use_ocr_fallback:
                # Image-only pages need OCR because PyMuPDF cannot extract text where no text layer exists.
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                ocr_text = extract_ocr_lines(pix.tobytes("png")).strip()
                if ocr_text:
                    parts.append(ocr_text)
                    used_ocr = True

    return PdfExtractionResult(text="\n\n".join(part for part in parts if part), used_ocr=used_ocr)


def resolve_pdf_path(settings: Settings, row: pd.Series) -> Path:
    source_pdf = clean_value(row.get("source_pdf"))
    if source_pdf:
        candidate = settings.pdf_dir / source_pdf
        if candidate.exists():
            return candidate

    patent_id = clean_value(row.get("patent_id"))
    if patent_id:
        candidate = settings.pdf_dir / f"{patent_id}.pdf"
        if candidate.exists():
            return candidate

    return settings.pdf_dir / (source_pdf or "")


def build_patent_record(settings: Settings, row: pd.Series) -> PatentRecord:
    pdf_path = resolve_pdf_path(settings, row)
    parse_status = "pending"
    parse_error = None
    full_text = ""

    if pdf_path.exists():
        try:
            extraction_result = extract_pdf_text(pdf_path, use_ocr_fallback=settings.use_ocr_fallback)
            full_text = extraction_result.text
            if full_text.strip():
                parse_status = "success_ocr" if extraction_result.used_ocr else "success"
            else:
                parse_status = "empty_text"
            if parse_status == "empty_text":
                parse_error = "PDF text extraction returned empty content"
        except Exception as exc:  # noqa: BLE001
            parse_status = "extract_failed"
            parse_error = str(exc)
    else:
        parse_status = "missing_pdf"
        parse_error = f"Missing PDF: {pdf_path.name}"

    title = clean_value(row.get("title_translated")) or clean_value(row.get("title_original")) or "Untitled"
    abstract = clean_value(row.get("abstract_translated")) or clean_value(row.get("abstract_original"))

    patent_id = clean_value(row.get("patent_id"))
    if patent_id is None:
        raise ValueError("Missing patent_id column value")

    return PatentRecord(
        patent_id=patent_id,
        title=title,
        assignee=clean_value(row.get("assignee")),
        filing_date=clean_value(row.get("filing_date")),
        ipc_main=clean_value(row.get("ipc_main")),
        ipc_all=clean_value(row.get("ipc_all")),
        abstract=abstract,
        claim_1=clean_value(row.get("claim_1")),
        claims_text=clean_value(row.get("claims_text")),
        full_text=full_text,
        source_pdf=pdf_path.name if pdf_path.name else clean_value(row.get("source_pdf")),
        parse_status=parse_status,
        parse_error=parse_error,
    )


def write_failure_log(log_path: Path, failures: list[dict[str, str]]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["patent_id", "source_pdf", "parse_status", "parse_error"])
        writer.writeheader()
        writer.writerows(failures)


def log_activity(
    activity_logger: ActivityLogger,
    record: PatentRecord,
    row_index: int,
    total_rows: int,
) -> None:
    activity_logger.write(
        ActivityLogEntry(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            row_index=row_index,
            total_rows=total_rows,
            patent_id=record.patent_id,
            source_pdf=record.source_pdf or "",
            parse_status=record.parse_status,
            parse_error=record.parse_error or "",
            used_ocr=record.parse_status == "success_ocr",
            text_length=len(record.full_text),
        )
    )


def ingest_patents(settings: Settings, limit: int | None = None) -> IngestStats:
    dataframe = load_metadata(settings.metadata_path)
    if limit is not None:
        dataframe = dataframe.head(limit)

    connection = connect(settings.db_path)
    initialize_database(connection)
    activity_logger = ActivityLogger(settings.parse_activity_log_path)

    imported_rows = 0
    parsed_pdfs = 0
    failures: list[dict[str, str]] = []
    total_rows = len(dataframe.index)

    try:
        for row_index, (_, row) in enumerate(dataframe.iterrows(), start=1):
            record = build_patent_record(settings, row)
            connection.execute(UPSERT_SQL, asdict(record))
            imported_rows += 1
            log_activity(activity_logger, record, row_index=row_index, total_rows=total_rows)

            if record.parse_status.startswith("success"):
                parsed_pdfs += 1
            else:
                failures.append(
                    {
                        "patent_id": record.patent_id,
                        "source_pdf": record.source_pdf or "",
                        "parse_status": record.parse_status,
                        "parse_error": record.parse_error or "",
                    }
                )

            if imported_rows % settings.commit_interval == 0:
                connection.commit()

            if imported_rows % settings.progress_interval == 0 or imported_rows == total_rows:
                print(
                    "Progress {current}/{total} | success={success} | failures={failures}".format(
                        current=imported_rows,
                        total=total_rows,
                        success=parsed_pdfs,
                        failures=len(failures),
                    )
                )

        connection.commit()
    finally:
        activity_logger.close()
        connection.close()

    write_failure_log(settings.parse_failure_log_path, failures)
    return IngestStats(
        total_rows=total_rows,
        imported_rows=imported_rows,
        parsed_pdfs=parsed_pdfs,
        failed_pdfs=len(failures),
    )


def get_connection(settings: Settings) -> sqlite3.Connection:
    return connect(settings.db_path)
