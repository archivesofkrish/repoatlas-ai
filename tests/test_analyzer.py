from pathlib import Path

from repoatlas.analyzer import analyze_repository


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


def test_syntax_error_is_warning_not_crash(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    report = analyze_repository(tmp_path)
    assert report.symbols == []
    assert any("SyntaxError" in warning for warning in report.warnings)
