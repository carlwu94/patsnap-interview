from __future__ import annotations

import sqlite3
from typing import Any


def _escape_fts_keyword(keyword: str) -> str:
    cleaned = keyword.strip().replace('"', '""')
    return f'"{cleaned}"'


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def search_by_keyword(
    connection: sqlite3.Connection,
    keyword: str | None = None,
    assignee: str | None = None,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    parameters: list[Any] = []
    normalized_keyword = keyword.strip() if keyword else None

    if normalized_keyword:
        filters.append("patents_fts MATCH ?")
        parameters.append(_escape_fts_keyword(normalized_keyword))

    if assignee:
        filters.append("p.assignee LIKE ?")
        parameters.append(f"%{assignee.strip()}%")

    if year_start is not None:
        filters.append("CAST(substr(p.filing_date, 1, 4) AS INTEGER) >= ?")
        parameters.append(year_start)

    if year_end is not None:
        filters.append("CAST(substr(p.filing_date, 1, 4) AS INTEGER) <= ?")
        parameters.append(year_end)

    if not filters:
        raise ValueError("At least one search filter must be provided.")

    parameters.append(limit)
    where_clause = " AND ".join(filters)
    if normalized_keyword:
        sql = f"""
            SELECT
                p.patent_id,
                p.title,
                p.assignee,
                p.filing_date,
                p.ipc_main,
                p.parse_status,
                bm25(patents_fts) AS score
            FROM patents_fts
            JOIN patents AS p ON p.rowid = patents_fts.rowid
            WHERE {where_clause}
            ORDER BY score ASC, p.filing_date DESC, p.patent_id ASC
            LIMIT ?
        """
    else:
        sql = f"""
            SELECT
                p.patent_id,
                p.title,
                p.assignee,
                p.filing_date,
                p.ipc_main,
                p.parse_status,
                NULL AS score
            FROM patents AS p
            WHERE {where_clause}
            ORDER BY p.filing_date DESC, p.patent_id ASC
            LIMIT ?
        """
    rows = connection.execute(sql, parameters).fetchall()
    return _rows_to_dicts(rows)


def get_patent_by_id(connection: sqlite3.Connection, patent_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM patents WHERE patent_id = ?",
        (patent_id,),
    ).fetchone()
    return dict(row) if row else None


def get_assignee_trend(
    connection: sqlite3.Connection,
    assignee: str,
    start_year: int,
    end_year: int,
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            CAST(substr(filing_date, 1, 4) AS INTEGER) AS year,
            COUNT(*) AS patent_count
        FROM patents
        WHERE assignee LIKE ?
          AND filing_date IS NOT NULL
          AND CAST(substr(filing_date, 1, 4) AS INTEGER) BETWEEN ? AND ?
        GROUP BY year
        ORDER BY year ASC
    """
    rows = connection.execute(sql, (f"%{assignee.strip()}%", start_year, end_year)).fetchall()
    trend = {int(row["year"]): int(row["patent_count"]) for row in rows}
    return [
        {"year": year, "patent_count": trend.get(year, 0)}
        for year in range(start_year, end_year + 1)
    ]


def list_assignees(
    connection: sqlite3.Connection,
    keyword: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    filters = ["assignee IS NOT NULL", "trim(assignee) != ''"]
    parameters: list[Any] = []

    if keyword:
        filters.append("assignee LIKE ?")
        parameters.append(f"%{keyword.strip()}%")

    parameters.append(limit)
    where_clause = " AND ".join(filters)
    rows = connection.execute(
        f"""
        SELECT assignee, COUNT(*) AS patent_count
        FROM patents
        WHERE {where_clause}
        GROUP BY assignee
        ORDER BY patent_count DESC, assignee COLLATE NOCASE ASC
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    return _rows_to_dicts(rows)


def get_top_ipc(connection: sqlite3.Connection, top_n: int = 10) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT ipc_main, COUNT(*) AS patent_count
        FROM patents
        WHERE ipc_main IS NOT NULL AND ipc_main != ''
        GROUP BY ipc_main
        ORDER BY patent_count DESC, ipc_main ASC
        LIMIT ?
        """,
        (top_n,),
    ).fetchall()
    return _rows_to_dicts(rows)
