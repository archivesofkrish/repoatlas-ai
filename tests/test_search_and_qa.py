from pathlib import Path

from repoatlas.qa import answer_question, validate_citation
from repoatlas.search import search_repository


def test_search_returns_line_addressable_evidence(tmp_path: Path):
    source = "\n".join([
        "def unrelated():",
        "    return 1",
        "",
        "def verify_token(token):",
        "    return token == 'valid'",
    ])
    (tmp_path / "auth.py").write_text(source, encoding="utf-8")
    hits = search_repository(tmp_path, "verify token", top_k=3)
    assert hits
    assert hits[0].path == "auth.py"
    assert hits[0].start_line <= 4 <= hits[0].end_line
    assert "verify_token" in hits[0].excerpt


def test_answer_includes_revision_scoped_citation_and_validates_it(tmp_path: Path):
    source = "def create_user(name):\n    return name\n"
    (tmp_path / "service.py").write_text(source, encoding="utf-8")
    response = answer_question(tmp_path, "create user")
    assert response["evidence"]
    citation = response["evidence"][0]["citation"]
    assert citation["revision"] is None
    assert validate_citation(tmp_path, citation)


def test_citation_rejects_traversal(tmp_path: Path):
    assert not validate_citation(
        tmp_path, {"path": "../outside", "start_line": 1, "end_line": 1}
    )


def test_search_citation_points_at_matching_line_not_context(tmp_path: Path):
    source = "# Authentication module\n\ndef verify_token(token):\n    return token\n"
    (tmp_path / "auth.py").write_text(source, encoding="utf-8")
    hit = search_repository(tmp_path, "verify token")[0]
    assert hit.start_line == 3
    assert hit.end_line == 3
    assert "1: # Authentication" in hit.excerpt
