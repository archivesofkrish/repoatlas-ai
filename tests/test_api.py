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



def test_api_answer_uses_configured_provider_and_returns_cited_claims(tmp_path: Path, monkeypatch):
    (tmp_path / "auth.py").write_text(
        "def authenticate_token(token):\n    return token is not None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())

    class FakeProvider:
        name = "fake"
        model = "test-model"

        def generate(self, *, question, evidence):
            assert question == "How are authentication tokens checked?"
            return {
                "claims": [{"text": "A token check exists.", "evidence_ids": ["E1"]}],
                "insufficient_evidence": False,
                "open_questions": [],
            }

    from repoatlas import llm

    monkeypatch.setattr(
        llm.OpenAIResponsesProvider,
        "from_env",
        classmethod(lambda cls: FakeProvider()),
    )
    response = TestClient(api.app).post(
        "/v1/answer",
        json={"path": ".", "question": "How are authentication tokens checked?"},
    )

    assert response.status_code == 200
    assert response.json()["generation_status"] == "generated"
    assert response.json()["claims"][0]["evidence"][0]["id"] == "E1"


def test_api_answer_requires_explicit_provider_configuration(tmp_path: Path, monkeypatch):
    (tmp_path / "auth.py").write_text(
        "def authenticate_token(token):\n    return token is not None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())
    from repoatlas import llm

    monkeypatch.setattr(
        llm.OpenAIResponsesProvider,
        "from_env",
        classmethod(lambda cls: None),
    )
    response = TestClient(api.app).post(
        "/v1/answer",
        json={"path": ".", "question": "How are authentication tokens checked?"},
    )
    assert response.status_code == 503



def test_api_answer_skips_provider_when_no_evidence_exists(tmp_path: Path, monkeypatch):
    from repoatlas import llm

    (tmp_path / "auth.py").write_text(
        "def authenticate_token(token):\n    return token is not None\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())
    monkeypatch.setattr(
        llm.OpenAIResponsesProvider,
        "from_env",
        classmethod(lambda cls: None),
    )

    response = TestClient(api.app).post(
        "/v1/answer",
        json={"path": ".", "question": "quantum nebula telescope"},
    )
    assert response.status_code == 200
    assert response.json()["generation_status"] == "no_evidence"


def test_hybrid_search_rejects_non_finite_lexical_weight(tmp_path: Path, monkeypatch):
    (tmp_path / "core.py").write_text(
        "def authenticate(token):\\n    return bool(token)\\n", encoding="utf-8"
    )
    monkeypatch.setattr(api, "ALLOWED_ROOT", tmp_path.resolve())
    client = TestClient(api.app)

    response = client.post(
        "/v1/hybrid-search",
        content=b'{"path":".","query":"authenticate","lexical_weight":NaN}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422