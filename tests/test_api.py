from pathlib import Path

from fastapi.testclient import TestClient

from repoatlas import api


def test_api_health_search_and_path_confinement(tmp_path: Path, monkeypatch):
    (tmp_path / "core.py").write_text(
        "def authenticate(token):\n    return bool(token)\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text(
        "from core import authenticate\n", encoding="utf-8"
    )
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())
    client = TestClient(api.app)

    assert client.get("/health").status_code == 200
    response = client.post("/v1/search", json={"path": ".", "query": "authenticate token"})
    assert response.status_code == 200
    assert response.json()["results"]
    assert response.json()["results"][0]["sha256"]
    assert response.json()["results"][0]["snapshot_id"]
    hybrid_response = client.post(
        "/v1/hybrid-search",
        json={"path": ".", "query": "authenticate token"},
    )
    assert hybrid_response.status_code == 200
    assert hybrid_response.json()["retrieval"] == "lexical+graph"
    assert hybrid_response.json()["results"]
    graph_response = client.post("/v1/graph", json={"path": "."})
    assert graph_response.status_code == 200
    assert graph_response.json()["stats"]["imports"] >= 1
    impact_response = client.post(
        "/v1/impact", json={"path": ".", "target": "core.py"}
    )
    assert impact_response.status_code == 200
    assert impact_response.json()["affected"][0]["path"] == "app.py"
    assert client.post("/v1/scan", json={"path": "../"}).status_code == 400
    assert client.post("/v1/scan", json={"path": "does-not-exist"}).status_code == 400
