from __future__ import annotations

from fastmcp import FastMCP

from app.config import get_settings
from app.db.connection import connect
from app.services.patent_query import (
    get_assignee_trend,
    get_patent_by_id,
    get_top_ipc,
    list_assignees,
    search_by_keyword,
)


def create_server() -> FastMCP:
    mcp = FastMCP(
        name="Patent Query Tools",
        instructions="Tools for searching lithium-ion battery patents stored in a local SQLite database.",
    )
    settings = get_settings()

    @mcp.tool(name="search_patents", description="Search patents by keyword with optional assignee and filing year filters.")
    def search_patents(
        keyword: str | None = None,
        assignee: str | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        connection = connect(settings.db_path)
        try:
            return search_by_keyword(connection, keyword, assignee, year_start, year_end, limit)
        finally:
            connection.close()

    @mcp.tool(name="get_patent_details", description="Get the full patent record, including extracted full text, by patent id.")
    def get_patent_details(patent_id: str) -> dict | None:
        connection = connect(settings.db_path)
        try:
            return get_patent_by_id(connection, patent_id)
        finally:
            connection.close()

    @mcp.tool(name="get_top_ipc", description="Return the most frequent IPC main classes in the patent collection.")
    def get_top_ipc_tool(top_n: int = 10) -> list[dict]:
        connection = connect(settings.db_path)
        try:
            return get_top_ipc(connection, top_n)
        finally:
            connection.close()

    @mcp.tool(name="get_assignee_trend", description="Return yearly patent counts for an assignee within a year range.")
    def get_assignee_trend_tool(assignee: str, start_year: int, end_year: int) -> list[dict]:
        connection = connect(settings.db_path)
        try:
            return get_assignee_trend(connection, assignee, start_year, end_year)
        finally:
            connection.close()

    @mcp.tool(
        name="list_assignees",
        description="List distinct assignee/company names with patent counts. Use this to resolve canonical company names before assignee-based queries.",
    )
    def list_assignees_tool(keyword: str | None = None, limit: int = 100) -> list[dict]:
        connection = connect(settings.db_path)
        try:
            return list_assignees(connection, keyword, limit)
        finally:
            connection.close()

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
