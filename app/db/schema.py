from __future__ import annotations

import sqlite3


PATENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS patents (
    patent_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    assignee TEXT,
    filing_date TEXT,
    ipc_main TEXT,
    ipc_all TEXT,
    abstract TEXT,
    claim_1 TEXT,
    claims_text TEXT,
    full_text TEXT,
    source_pdf TEXT,
    parse_status TEXT NOT NULL DEFAULT 'pending',
    parse_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

PATENTS_ASSIGNEE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_patents_assignee ON patents (assignee)
"""

PATENTS_FILING_DATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_patents_filing_date ON patents (filing_date)
"""

PATENTS_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS patents_fts USING fts5(
    patent_id UNINDEXED,
    title,
    abstract,
    claims_text,
    full_text,
    content='patents',
    content_rowid='rowid'
)
"""

PATENTS_FTS_INSERT_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS patents_ai AFTER INSERT ON patents BEGIN
    INSERT INTO patents_fts(rowid, patent_id, title, abstract, claims_text, full_text)
    VALUES (new.rowid, new.patent_id, new.title, new.abstract, new.claims_text, new.full_text);
END
"""

PATENTS_FTS_DELETE_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS patents_ad AFTER DELETE ON patents BEGIN
    INSERT INTO patents_fts(patents_fts, rowid, patent_id, title, abstract, claims_text, full_text)
    VALUES ('delete', old.rowid, old.patent_id, old.title, old.abstract, old.claims_text, old.full_text);
END
"""

PATENTS_FTS_UPDATE_TRIGGER_SQL = """
CREATE TRIGGER IF NOT EXISTS patents_au AFTER UPDATE ON patents BEGIN
    INSERT INTO patents_fts(patents_fts, rowid, patent_id, title, abstract, claims_text, full_text)
    VALUES ('delete', old.rowid, old.patent_id, old.title, old.abstract, old.claims_text, old.full_text);
    INSERT INTO patents_fts(rowid, patent_id, title, abstract, claims_text, full_text)
    VALUES (new.rowid, new.patent_id, new.title, new.abstract, new.claims_text, new.full_text);
END
"""


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(PATENTS_TABLE_SQL)
    connection.executescript(PATENTS_ASSIGNEE_INDEX_SQL)
    connection.executescript(PATENTS_FILING_DATE_INDEX_SQL)
    connection.executescript(PATENTS_FTS_SQL)
    connection.executescript(PATENTS_FTS_INSERT_TRIGGER_SQL)
    connection.executescript(PATENTS_FTS_DELETE_TRIGGER_SQL)
    connection.executescript(PATENTS_FTS_UPDATE_TRIGGER_SQL)
    connection.commit()