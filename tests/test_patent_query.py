from __future__ import annotations

from app.services.patent_query import (
    get_assignee_trend,
    get_patent_by_id,
    get_top_ipc,
    list_assignees,
    search_by_keyword,
)


def test_search_by_keyword_returns_matches(seeded_connection):
    results = search_by_keyword(seeded_connection, keyword="solid", limit=5)
    assert results
    assert results[0]["patent_id"] == "CNTEST001A"


def test_search_by_keyword_supports_assignee_and_year_without_keyword(seeded_connection):
    results = search_by_keyword(seeded_connection, assignee="CATL", year_start=2025, year_end=2025, limit=5)
    assert results == [
        {
            "patent_id": "CNTEST002A",
            "title": "Lithium cathode material",
            "assignee": "CATL",
            "filing_date": "2025-02-14",
            "ipc_main": "H01M4/525",
            "parse_status": "success",
            "score": None,
        }
    ]


def test_get_patent_by_id_returns_full_record(seeded_connection):
    result = get_patent_by_id(seeded_connection, "CNTEST002A")
    assert result is not None
    assert result["assignee"] == "CATL"
    assert result["ipc_main"] == "H01M4/525"


def test_get_assignee_trend_fills_missing_years(seeded_connection):
    trend = get_assignee_trend(seeded_connection, assignee="CATL", start_year=2023, end_year=2025)
    assert trend == [
        {"year": 2023, "patent_count": 0},
        {"year": 2024, "patent_count": 1},
        {"year": 2025, "patent_count": 1},
    ]


def test_get_top_ipc_orders_by_count(seeded_connection):
    top_ipc = get_top_ipc(seeded_connection, top_n=2)
    assert top_ipc[0] == {"ipc_main": "H01M4/525", "patent_count": 2}


def test_list_assignees_returns_distinct_names_with_counts(seeded_connection):
    assignees = list_assignees(seeded_connection, limit=10)
    assert assignees == [
        {"assignee": "CATL", "patent_count": 2},
        {"assignee": "BYD", "patent_count": 1},
    ]
