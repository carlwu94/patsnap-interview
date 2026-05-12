from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.db.ingest import ingest_patents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load patent metadata and PDF text into SQLite.")
    parser.add_argument("--limit", type=int, default=None, help="Only import the first N rows for smoke testing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stats = ingest_patents(get_settings(), limit=args.limit)
    print(
        "Imported {imported}/{total} rows; parsed PDFs: {parsed}; failures: {failed}".format(
            imported=stats.imported_rows,
            total=stats.total_rows,
            parsed=stats.parsed_pdfs,
            failed=stats.failed_pdfs,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())