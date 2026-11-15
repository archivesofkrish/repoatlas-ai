from pathlib import Path

from repoatlas.scanner import scan_files



def test_scanner_indexes_text_and_excludes_sensitive_and_generated(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=do-not-read-this-value\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("ignored", encoding="utf-8")
    (tmp_path / "binary.py").write_bytes(b"\x00\xff")
    files, excluded, warnings = scan_files(tmp_path)
    assert [item.path for item in files] == ["src/main.py"]
    assert excluded["sensitive"] == 1
    assert excluded["ignored"] == 1
    assert excluded["binary_or_unreadable"] == 1
    assert warnings == []

def test_scanner_respects_file_size_limit(tmp_path: Path):
    (tmp_path / "large.py").write_text("x" * 100, encoding="utf-8")
    files, excluded, _ = scan_files(tmp_path, max_file_bytes=10)
    assert files == []
    assert excluded["oversized"] == 1

def test_scanner_does_not_follow_file_symlinks(tmp_path: Path):
    outside = tmp_path.parent / "outside-secret.py"
    outside.write_text("secret = 'not indexed'\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        return
    files, excluded, _ = scan_files(tmp_path)
    assert files == []
    assert excluded["symlink"] == 1
