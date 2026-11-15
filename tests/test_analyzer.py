from pathlib import Path

from repoatlas.analyzer import analyze_repository, analyze_snapshot
from repoatlas.scanner import create_snapshot


def test_extracts_nested_python_symbols_and_imports(tmp_path: Path):
    source = "\n".join([
        "import json",
        "from pathlib import Path",
        "",
        "class Service:",
        "    def run(self):",
        "        async def inner():",
        "            return Path('.')",
        "        return inner",
    ])
    (tmp_path / "module.py").write_text(source, encoding="utf-8")
    report = analyze_repository(tmp_path)
    names = {symbol.qualified_name for symbol in report.symbols}
    assert {"Service", "Service.run", "Service.run.inner"} <= names
    assert report.imports["module.py"] == ["json", "pathlib"]
    assert report.import_details["module.py"][1]["names"] == ["Path"]
    assert report.import_details["module.py"][1]["line"] == 2


def test_syntax_error_is_warning_not_crash(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    report = analyze_repository(tmp_path)
    assert report.symbols == []
    assert any("SyntaxError" in warning for warning in report.warnings)


def test_analyzer_uses_captured_source_after_disk_file_changes(tmp_path: Path):
    source = tmp_path / "module.py"
    source.write_text("def captured_symbol():\n    return 1\n", encoding="utf-8")
    snapshot = create_snapshot(tmp_path)

    source.write_text("def later_symbol():\n    return 2\n", encoding="utf-8")
    report = analyze_snapshot(snapshot)

    names = {symbol.name for symbol in report.symbols}
    assert "captured_symbol" in names
    assert "later_symbol" not in names
    assert report.snapshot_id == snapshot.snapshot_id
