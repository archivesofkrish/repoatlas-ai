import subprocess
from pathlib import Path

import pytest

from repoatlas.review import render_change_review_html, review_changes


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def _repository(root: Path) -> None:
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "repoatlas-tests@example.invalid")
    _git(root, "config", "user.name", "RepoAtlas tests")


def test_review_tracks_transitive_dependants_and_untracked_files(tmp_path: Path):
    root = tmp_path / "project"
    _repository(root)
    (root / "core.py").write_text("def calculate():\n    return 1\n", encoding="utf-8")
    (root / "service.py").write_text("import core\n", encoding="utf-8")
    (root / "api.py").write_text("import service\n", encoding="utf-8")
    _commit_all(root, "baseline")
    _git(root, "branch", "baseline")
    (root / "core.py").write_text("def calculate():\n    return 2\n", encoding="utf-8")
    (root / "new_module.py").write_text("VALUE = 3\n", encoding="utf-8")

    result = review_changes(root, base_ref="baseline")

    assert result["stats"]["changed_files"] == 2
    core = next(item for item in result["changes"] if item["path"] == "core.py")
    assert core["status"] == "M"
    assert [item["path"] for item in core["affected"]] == ["service.py", "api.py"]
    added = next(item for item in result["changes"] if item["path"] == "new_module.py")
    assert added["status"] == "A"
    assert added["tracked"] is False
    assert result["stats"]["affected_files"] == 2


def test_review_marks_deleted_files_as_unmapped(tmp_path: Path):
    root = tmp_path / "project"
    _repository(root)
    (root / "gone.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root, "baseline")
    _git(root, "branch", "baseline")
    (root / "gone.py").unlink()
    result = review_changes(root, base_ref="baseline")

    assert result["changes"][0]["status"] == "D"
    assert result["changes"][0]["in_snapshot"] is False
    assert result["changes"][0]["attention"] == "Unmapped"
    assert result["stats"]["unmapped_changes"] == 1


@pytest.mark.parametrize("ref", ["-bad", "main..HEAD", "main^{tree}", "", "../outside"])
def test_review_rejects_unsafe_ref_syntax(tmp_path: Path, ref: str):
    root = tmp_path / "project"
    _repository(root)
    with pytest.raises(ValueError, match="base_ref"):
        review_changes(root, base_ref=ref)


def test_review_requires_repository_root(tmp_path: Path):
    root = tmp_path / "project"
    _repository(root)
    child = root / "nested"
    child.mkdir()
    with pytest.raises(ValueError, match="repository root"):
        review_changes(child, base_ref="HEAD")


def test_review_rejects_missing_base_ref(tmp_path: Path):
    root = tmp_path / "project"
    _repository(root)
    with pytest.raises(ValueError, match="Git change review failed"):
        review_changes(root, base_ref="missing-branch")


def test_review_html_is_offline_and_escapes_script_sensitive_paths(tmp_path: Path):
    root = tmp_path / "project"
    _repository(root)
    (root / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root, "baseline")
    _git(root, "branch", "baseline")
    (root / "module-<script>.py").write_text("VALUE = 2\n", encoding="utf-8")
    result = review_changes(root, base_ref="baseline")
    output = render_change_review_html(result, tmp_path / "report" / "review.html")
    page = output.read_text(encoding="utf-8")

    assert output.exists()
    assert "RepoAtlas · Change Review" in page
    assert "cdn." not in page
    assert "\\u003cscript\\u003e" in page
    assert "module-<script>.py" not in page
