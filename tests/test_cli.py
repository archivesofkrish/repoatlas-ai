from pathlib import Path

from repoatlas.cli import main


def test_cli_scan_json(tmp_path: Path, capsys):
    (tmp_path / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    assert main(["scan", str(tmp_path), "--json"]) == 0
    output = capsys.readouterr().out
    assert '"files": 1' in output
    assert "hello" in output


def test_cli_hybrid_search(tmp_path: Path, capsys):
    (tmp_path / "core.py").write_text(
        "def authenticate(token):\n    return bool(token)\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from core import authenticate\n",
        encoding="utf-8",
    )
    assert main([
        "hybrid-search", str(tmp_path), "authenticate token", "--top-k", "5",
    ]) == 0
    output = capsys.readouterr().out
    assert "core.py" in output



def test_cli_answer_uses_grounded_answer_layer(tmp_path: Path, capsys, monkeypatch):
    import repoatlas.cli as cli

    def fake_answer(root, question, *, top_k):
        return {
            "answer": "Evidence-supported findings: token check exists [E1]",
            "generation_status": "generated",
            "top_k": top_k,
        }

    monkeypatch.setattr(cli, "generate_grounded_answer", fake_answer)
    assert main([
        "answer", str(tmp_path), "How are tokens checked?", "--top-k", "4",
    ]) == 0
    output = capsys.readouterr().out
    assert "Evidence-supported findings" in output
    assert '"top_k": 4' in output


def test_cli_answer_reports_missing_provider(tmp_path: Path, capsys, monkeypatch):
    import repoatlas.cli as cli
    from repoatlas.llm import ProviderError

    def unavailable(*_args, **_kwargs):
        raise ProviderError("No model provider is configured.")

    monkeypatch.setattr(cli, "generate_grounded_answer", unavailable)
    assert main(["answer", str(tmp_path), "Explain token validation"]) == 2
    assert "No model provider is configured." in capsys.readouterr().err


def test_cli_architecture_writes_self_contained_explorer(tmp_path: Path, capsys):
    (tmp_path / "core.py").write_text("def authenticate():\n    return True\n", encoding="utf-8")
    (tmp_path / "api.py").write_text("import core\n", encoding="utf-8")
    output = tmp_path / "artifacts" / "architecture.html"

    assert main(["architecture", str(tmp_path), "--output", str(output)]) == 0

    content = output.read_text(encoding="utf-8")
    assert "RepoAtlas Architecture Explorer" in content
    assert "Architecture explorer written to:" in capsys.readouterr().out


def test_cli_architecture_json_mode(tmp_path: Path, capsys):
    (tmp_path / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert main(["architecture", str(tmp_path), "--json"]) == 0

    output = capsys.readouterr().out
    assert '"dependency_cycles": 0' in output
    assert '"files": 1' in output
