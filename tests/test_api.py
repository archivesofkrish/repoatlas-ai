from pathlib import Path

from fastapi.testclient import TestClient

from repoatlas import api


def test_api_health_search_and_path_confinement(tmp_path: Path, monkeypatch):
    (tmp_path / "app.py").write_text("def authenticate(token):\\n    return bool(token)\\n", encoding="utf-8")
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())
    client = TestClient(api.app)

    assert client.get("/health").status_code == 200
    response = client.post("/v1/search", json={"path": ".", "query": "authenticate token"})
    assert response.status_code == 200
    assert response.json()["results"]
    assert client.post("/v1/scan", json={"path": "../"}).status_code == 400
    assert client.post("/v1/scan", json={"path": "does-not-exist"}).status_code == 400
