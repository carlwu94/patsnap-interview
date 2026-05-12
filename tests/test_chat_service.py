from __future__ import annotations

from app.agent.chat_service import _normalize_tool_arguments


def test_normalize_tool_arguments_uses_resolved_assignee_and_drops_noisy_keyword():
    arguments = {
        "keyword": "宁德时代在 2026年期间申请的",
        "assignee": None,
        "year_start": 2026,
        "year_end": 2026,
        "limit": 10,
    }

    normalized = _normalize_tool_arguments(
        "search_patents",
        arguments,
        {"宁德时代": "宁德时代新能源科技股份有限公司"},
    )

    assert normalized == {
        "keyword": None,
        "assignee": "宁德时代新能源科技股份有限公司",
        "year_start": 2026,
        "year_end": 2026,
        "limit": 10,
    }