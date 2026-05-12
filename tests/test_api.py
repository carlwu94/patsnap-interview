from __future__ import annotations

from fastapi.testclient import TestClient

from app.web.main import create_app


def test_search_api(monkeypatch, test_settings, seeded_connection):
    monkeypatch.setattr("app.web.routes.api.get_settings", lambda: test_settings)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/search", json={"keyword": "lithium", "limit": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["patent_id"] == "CNTEST002A"


def test_chat_api_uses_fallback_tool_call(monkeypatch, test_settings, seeded_connection):
    monkeypatch.setattr("app.web.routes.api.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.mcp.server.get_settings", lambda: test_settings)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "最热门的2个IPC分类号是什么？"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"][0]["tool"] == "get_top_ipc"
    assert payload["data"][0]["ipc_main"] == "H01M4/525"


def test_chat_api_lists_assignees_via_mcp(monkeypatch, test_settings, seeded_connection):
    monkeypatch.setattr("app.web.routes.api.get_settings", lambda: test_settings)
    monkeypatch.setattr("app.mcp.server.get_settings", lambda: test_settings)
    app = create_app()
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "列出所有公司的名称"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_calls"][0]["tool"] == "list_assignees"
    assert payload["data"][0] == {"assignee": "CATL", "patent_count": 2}
    assert "CATL" in payload["answer"]
    assert "BYD" in payload["answer"]
