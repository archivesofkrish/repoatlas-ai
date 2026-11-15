from pathlib import Path

import pytest

from repoatlas.analyzer import analyze_repository
from repoatlas.graph import build_graph
from repoatlas.parsing import parse_tree_sitter_file
from repoatlas.scanner import scan_files


def test_scanner_excludes_nested_google_cloud_credentials(tmp_path: Path):
    credentials = tmp_path / ".config" / "gcloud"
    credentials.mkdir(parents=True)
    (credentials / "application_default_credentials.json").write_text(
        '{"refresh_token":"do-not-index"}', encoding="utf-8"
    )
    (tmp_path / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")

    files, excluded, _warnings = scan_files(tmp_path)

    assert [item.path for item in files] == ["app.py"]
    assert excluded["ignored"] >= 1


def test_python_fromlist_resolves_src_layout_submodule(tmp_path: Path):
    source = tmp_path / "src"
    package = source / "pkg"
    package.mkdir(parents=True)
    (source / "api.py").write_text("from pkg import helpers\n", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helpers.py").write_text(
        "def normalize(value):\n    return value.strip()\n", encoding="utf-8"
    )

    graph = build_graph(analyze_repository(tmp_path))
    assert any(
        edge["source"] == "src/api.py"
        and edge["target"] == "src/pkg/helpers.py"
        and edge["resolved"]
        for edge in graph["edges"]
    )


def test_graph_does_not_resolve_matching_basename_from_unrelated_directory(tmp_path: Path):
    source = tmp_path / "src"
    unrelated = tmp_path / "vendor" / "service"
    source.mkdir(parents=True)
    unrelated.mkdir(parents=True)
    (source / "consumer.py").write_text("import service\n", encoding="utf-8")
    (unrelated / "service.py").write_text("def run():\n    pass\n", encoding="utf-8")

    graph = build_graph(analyze_repository(tmp_path))
    assert any(
        edge["source"] == "src/consumer.py"
        and edge["target"] == "service"
        and edge["resolved"] is False
        for edge in graph["edges"]
    )


def test_python_calls_in_decorators_and_default_expressions_are_indexed(tmp_path: Path):
    (tmp_path / "module.py").write_text(
        "def decorate(fn):\n    return fn\n"
        "def build_value():\n    return 1\n"
        "@decorate\n"
        "def run(value=build_value()):\n    return value\n",
        encoding="utf-8",
    )

    report = analyze_repository(tmp_path)
    targets = {call["target"] for call in report.calls["module.py"]}
    assert {"decorate", "build_value"} <= targets


def test_javascript_arrow_function_declaration_is_indexed_when_cached():
    result = parse_tree_sitter_file(
        "src/app.js",
        "export const start = async () => { return true; };\n",
    )
    if result["warning"] and "not installed" in result["warning"]:
        pytest.skip(result["warning"])
    assert any(symbol.name == "start" and symbol.kind == "function" for symbol in result["symbols"])


def test_go_grouped_import_declaration_extracts_each_path_when_cached():
    result = parse_tree_sitter_file(
        "main.go",
        'package main\nimport (\n  "fmt"\n  "os"\n)\nfunc main() {}\n',
    )
    if result["warning"] and "not installed" in result["warning"]:
        pytest.skip(result["warning"])
    assert {item["target"] for item in result["imports"]} >= {"fmt", "os"}


def test_quoted_c_include_is_marked_as_source_relative_when_cached():
    result = parse_tree_sitter_file(
        "src/main.c",
        '#include "internal.h"\nint main(void) { return 0; }\n',
    )
    if result["warning"] and "not installed" in result["warning"]:
        pytest.skip(result["warning"])
    assert any(item["target"] == "./internal.h" for item in result["imports"])

def test_tree_sitter_traversal_has_a_depth_limit_when_cached():
    nested = "(" * 600 + "1" + ")" * 600
    result = parse_tree_sitter_file("src/deep.js", f"function run() {{ return {nested}; }}")
    if result["warning"] and "not installed" in result["warning"]:
        pytest.skip(result["warning"])
    assert "depth limit" in (result["warning"] or "").lower()
