from pathlib import Path

import pytest

from repoatlas.hybrid import hybrid_search_repository
from repoatlas.qa import validate_citation
from repoatlas.search import search_repository


def _dependency_fixture(root: Path):
    security = root / "src" / "security"
    api = root / "src" / "api"
    services = root / "src" / "services"
    for directory in (security, api, services):
        directory.mkdir(parents=True, exist_ok=True)
    (security / "policy.py").write_text(
        '"""Session token expiry enforcement policy."""\n'
        "def enforce_expiry(token, now):\n"
        "    return token.expires_at > now\n",
        encoding="utf-8",
    )
    (api / "routes.py").write_text(
        "from security.policy import enforce_expiry\n"
        "def handle(request):\n"
        "    return enforce_expiry(request.token, request.now)\n",
        encoding="utf-8",
    )
    (services / "workflow.py").write_text(
        "from api.routes import handle\n"
        "def run(context):\n"
        "    return handle(context)\n",
        encoding="utf-8",
    )
    (root / "src" / "metrics.py").write_text(
        '"""A report about token expiry enforcement, not runtime policy."""\n'
        "def render(rows):\n"
        "    return {'token': len(rows), 'expiry': True, 'enforcement': True}\n",
        encoding="utf-8",
    )


def test_hybrid_search_expands_transitive_import_context_with_citations(tmp_path: Path):
    _dependency_fixture(tmp_path)
    query = "session token expiry enforcement"
    lexical_paths = {
        hit.path for hit in search_repository(tmp_path, query, top_k=10)
    }
    hits = hybrid_search_repository(tmp_path, query, top_k=10, graph_depth=2)
    by_path = {hit.path: hit for hit in hits}

    assert "src/services/workflow.py" not in lexical_paths
    assert "src/services/workflow.py" in by_path
    assert "Graph-expanded evidence" in by_path["src/services/workflow.py"].reason
    assert "distance 2" in by_path["src/services/workflow.py"].reason
    assert "src/api/routes.py" in by_path["src/services/workflow.py"].reason
    hit = by_path["src/services/workflow.py"]
    assert validate_citation(tmp_path, {
        "path": hit.path, "start_line": hit.start_line, "end_line": hit.end_line,
    })


def test_hybrid_search_keeps_lexical_only_results(tmp_path: Path):
    (tmp_path / "config.py").write_text(
        "def rotate_signing_key():\n    return 'rotated'\n",
        encoding="utf-8",
    )
    hits = hybrid_search_repository(tmp_path, "rotate signing key", top_k=5)
    assert hits
    assert hits[0].path == "config.py"
    assert "Lexical" in hits[0].reason or "Matched terms" in hits[0].reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {"graph_depth": 0},
        {"graph_depth": 4},
        {"lexical_weight": 0.0},
        {"lexical_weight": 1.0},
        {"context_lines": 21},
    ],
)
def test_hybrid_search_rejects_invalid_options(tmp_path: Path, kwargs):
    (tmp_path / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
    with pytest.raises(ValueError):
        hybrid_search_repository(tmp_path, "run", **kwargs)


def test_hybrid_search_reads_each_source_file_only_once(tmp_path: Path, monkeypatch):
    import repoatlas.scanner as scanner

    _dependency_fixture(tmp_path)
    original = scanner._safe_text
    read_paths = []

    def counted_read(path, max_file_bytes, **kwargs):
        read_paths.append(path)
        return original(path, max_file_bytes, **kwargs)

    monkeypatch.setattr(scanner, "_safe_text", counted_read)
    hits = hybrid_search_repository(tmp_path, "session token expiry enforcement")

    assert hits
    assert len(read_paths) == 4
    assert len(set(read_paths)) == 4
