from pathlib import Path

import pytest

from repoatlas.analyzer import analyze_repository
from repoatlas.architecture import build_architecture_report, render_architecture_html
from repoatlas.graph import build_graph


def _report(root: Path):
    analysis = analyze_repository(root)
    return build_architecture_report(analysis, build_graph(analysis))


def test_architecture_report_detects_cycles_packages_and_hotspots(tmp_path: Path):
    services = tmp_path / "services"
    services.mkdir()
    (tmp_path / "main.py").write_text("import services.auth\n", encoding="utf-8")
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "auth.py").write_text("import services.tokens\n", encoding="utf-8")
    (services / "tokens.py").write_text("import services.auth\n", encoding="utf-8")
    (tmp_path / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")

    result = _report(tmp_path)

    assert result["stats"]["files"] == 5
    assert result["stats"]["dependency_cycles"] == 1
    assert result["stats"]["files_in_cycles"] == 2
    assert result["stats"]["isolated_files"] >= 1
    assert result["cycles"] == [["services/auth.py", "services/tokens.py"]]
    auth = next(item for item in result["files"] if item["path"] == "services/auth.py")
    assert auth["in_cycle"] is True
    assert auth["fan_in"] == 2
    assert any(
        item["source"] == "." and item["target"] == "services"
        for item in result["package_dependencies"]
    )
    root_package = next(item for item in result["packages"] if item["name"] == ".")
    service_package = next(item for item in result["packages"] if item["name"] == "services")
    assert root_package["dependency_count"] == 1
    assert root_package["cross_package_imports"] == 1
    assert service_package["dependant_count"] == 1
    assert service_package["cycle_file_count"] == 2
    assert root_package["dependency_packages"] == ["services"]


def test_architecture_report_is_deterministic_and_keeps_unresolved_count(tmp_path: Path):
    (tmp_path / "main.py").write_text(
        "import external_package\n\ndef run():\n    return external_package.call()\n",
        encoding="utf-8",
    )
    (tmp_path / "unused.py").write_text("VALUE = 2\n", encoding="utf-8")

    first = _report(tmp_path)
    second = _report(tmp_path)

    assert first == second
    assert first["stats"]["unresolved_imports"] >= 1
    assert first["stats"]["isolated_files"] >= 1


def test_html_explorer_is_self_contained_and_escapes_untrusted_paths(tmp_path: Path):
    (tmp_path / "<script>.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = _report(tmp_path)
    result["repository"] = "</script>"
    destination = render_architecture_html(result, tmp_path / "out" / "map.html")

    html = destination.read_text(encoding="utf-8")

    assert "<svg" in html
    assert "RepoAtlas Architecture Observatory" in html
    assert "Package map" in html
    assert 'id="package-graph"' in html
    assert "https://cdn" not in html
    assert "src=" not in html
    assert html.count("</script>") == 2
    assert "&lt;/script&gt;" in html
    assert "\\u003c/script\\u003e" in html
    assert "\\u003cscript\\u003e.py" in html
    assert "repository" in html.lower()


@pytest.mark.parametrize("max_nodes", [0, 19, 501, True])
def test_html_explorer_rejects_invalid_node_limits(tmp_path: Path, max_nodes):
    with pytest.raises(ValueError, match="max_nodes"):
        render_architecture_html({"files": []}, tmp_path / "map.html", max_nodes=max_nodes)
