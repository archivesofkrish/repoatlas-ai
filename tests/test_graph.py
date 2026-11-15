from pathlib import Path

from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph, impact_analysis


def test_python_import_graph_and_transitive_impact(tmp_path: Path):
    (tmp_path / "core.py").write_text("def calculate():\n    return 42\n", encoding="utf-8")
    (tmp_path / "service.py").write_text("from core import calculate\n", encoding="utf-8")
    (tmp_path / "api.py").write_text("import service\n", encoding="utf-8")
    report = analyze_repository(tmp_path)
    graph = build_graph(report)
    result = impact_analysis(graph, "core.py")
    assert [item["path"] for item in result["affected"]] == ["service.py", "api.py"]
    assert graph["stats"]["imports"] >= 2


def test_impact_rejects_unknown_target(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    graph = build_graph(analyze_repository(tmp_path))
    try:
        impact_analysis(graph, "missing.py")
    except ValueError:
        return
    raise AssertionError("unknown target should be rejected")
