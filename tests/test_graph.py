from pathlib import Path

from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph, impact_analysis


def test_python_import_graph_and_transitive_impact(tmp_path: Path):
    (tmp_path / "core.py").write_text(
        "def calculate():\n    return 42\n", encoding="utf-8"
    )
    (tmp_path / "service.py").write_text(
        "from core import calculate\n", encoding="utf-8"
    )
    (tmp_path / "api.py").write_text("import service\n", encoding="utf-8")
    graph = build_graph(analyze_repository(tmp_path))
    result = impact_analysis(graph, "core.py")
    assert [item["path"] for item in result["affected"]] == ["service.py", "api.py"]
    assert graph["stats"]["imports"] >= 2


def test_call_reference_resolves_unique_python_symbol(tmp_path: Path):
    source = "def calculate():\n    return 42\n\ndef run():\n    return calculate()\n"
    (tmp_path / "service.py").write_text(source, encoding="utf-8")
    graph = build_graph(analyze_repository(tmp_path))
    call_edges = [edge for edge in graph["edges"] if edge["kind"] == "calls"]
    assert len(call_edges) == 1
    assert call_edges[0]["resolved"] is True
    assert call_edges[0]["target"] == "service.py::calculate"


def test_relative_javascript_import_resolves_when_grammar_cached(tmp_path: Path):
    source_root = tmp_path / "src"
    source_root.mkdir()
    (source_root / "app.js").write_text(
        "import { start } from './worker.js';\nstart();\n", encoding="utf-8"
    )
    (source_root / "worker.js").write_text(
        "export function start() { return true; }\n", encoding="utf-8"
    )
    report = analyze_repository(tmp_path)
    if any("javascript" in warning and "not installed" in warning for warning in report.warnings):
        return
    graph = build_graph(report)
    assert any(
        edge["source"] == "src/app.js"
        and edge["target"] == "src/worker.js"
        and edge["resolved"]
        for edge in graph["edges"]
    ), (report.warnings, graph["edges"])


def test_impact_rejects_unknown_target(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    graph = build_graph(analyze_repository(tmp_path))
    try:
        impact_analysis(graph, "missing.py")
    except ValueError:
        return
    raise AssertionError("unknown target should be rejected")
