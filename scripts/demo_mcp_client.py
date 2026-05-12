from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.mcp.server import create_server


async def async_main() -> int:
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        assignee_result = await client.call_tool("list_assignees", {"limit": 10})
        search_result = await client.call_tool(
            "search_patents",
            {"keyword": "锂离子电池", "limit": 3},
        )
        search_items = search_result.structured_content.get("result") or []
        first_patent = search_items[0] if search_items else None

        detail_result = None
        trend_result = None
        if first_patent:
            detail_result = await client.call_tool(
                "get_patent_details",
                {"patent_id": first_patent["patent_id"]},
            )

            filing_year = int(str(first_patent.get("filing_date") or "2025")[:4])
            assignee = first_patent.get("assignee")
            if assignee:
                trend_result = await client.call_tool(
                    "get_assignee_trend",
                    {
                        "assignee": assignee,
                        "start_year": max(2000, filing_year - 2),
                        "end_year": filing_year,
                    },
                )

        ipc_result = await client.call_tool("get_top_ipc", {"top_n": 5})

    print("Tools:")
    print(json.dumps([tool.name for tool in tools], ensure_ascii=False, indent=2))
    print("\nlist_assignees:")
    print(json.dumps(assignee_result.structured_content, ensure_ascii=False, indent=2))
    print("\nsearch_patents:")
    print(json.dumps(search_result.structured_content, ensure_ascii=False, indent=2))
    if detail_result is not None:
        print("\nget_patent_details:")
        print(json.dumps(detail_result.structured_content, ensure_ascii=False, indent=2))
    if trend_result is not None:
        print("\nget_assignee_trend:")
        print(json.dumps(trend_result.structured_content, ensure_ascii=False, indent=2))
    print("\nget_top_ipc:")
    print(json.dumps(ipc_result.structured_content, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
