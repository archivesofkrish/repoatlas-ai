from pathlib import Path

from repoatlas.cli import main


def test_cli_scan_json(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("def hello():\\n    return 'world'\\n", encoding="utf-8")
    assert main(["scan", str(tmp_path), "--json"]) == 0
    output = capsys.readouterr().out
    assert '"files": 1' in output
    assert "hello" in output
