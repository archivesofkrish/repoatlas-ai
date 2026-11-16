import hashlib
import os
from pathlib import Path

import pytest

from repoatlas import scanner

from repoatlas.scanner import create_snapshot, scan_files


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


def test_snapshot_is_content_addressed_and_retains_captured_text(tmp_path: Path):
    source = tmp_path / "module.py"
    original = "def original_symbol():\n    return 1\n"
    source.write_text(original, encoding="utf-8")

    snapshot = create_snapshot(tmp_path)
    assert len(snapshot.documents) == 1
    assert isinstance(snapshot.excluded, tuple)
    assert isinstance(snapshot.warnings, tuple)
    document = snapshot.documents[0]
    assert document.metadata.path == "module.py"
    assert document.content == original
    assert document.metadata.sha256 == hashlib.sha256(original.encode()).hexdigest()

    source.write_text("def replacement_symbol():\n    return 2\n", encoding="utf-8")
    assert document.content == original
    assert create_snapshot(tmp_path).snapshot_id != snapshot.snapshot_id



def test_scanner_excludes_common_cli_credential_stores(tmp_path: Path):
    credential_files = {
        ".config/gh/hosts.yml": "github.com:\n  oauth_token: ghp_do-not-index-this-token\n",
        ".docker/config.json": '{"auths":{"registry.example":{"auth":"secret"}}}\n',
        ".kube/config": "users:\n- user:\n    token: do-not-index-this-token\n",
        ".azure/credentials": "[default]\nclient_secret=do-not-index-this-secret\n",
        ".netrc": "machine example login user password do-not-index-this-secret\n",
        ".npmrc": "//registry.example/:_authToken=do-not-index-this-token\n",
    }
    for relative, content in credential_files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "safe.py").write_text("def safe():\n    return True\n", encoding="utf-8")

    files, excluded, warnings = scan_files(tmp_path)
    indexed_paths = {item.path for item in files}

    assert indexed_paths == {"src/safe.py"}
    assert excluded["ignored"] >= 4
    assert excluded["sensitive"] >= 2
    assert warnings == []


def test_scanner_rejects_file_replaced_by_symlink_before_open(tmp_path: Path, monkeypatch):
    source = tmp_path / "module.py"
    outside = tmp_path / "outside.py"
    source.write_text("safe = True\n", encoding="utf-8")
    outside.write_text("secret = 'must not be read'\n", encoding="utf-8")

    probe = tmp_path / "symlink-probe"
    try:
        probe.symlink_to(outside)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is not available on this platform")

    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == source and not swapped:
            source.unlink()
            source.symlink_to(outside)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(scanner.os, "open", swap_then_open)
    result = scanner._safe_text(source, 1024, root=tmp_path)

    assert swapped is True
    assert result is None


def test_scanner_rejects_parent_directory_replaced_by_symlink(tmp_path: Path, monkeypatch):
    nested = tmp_path / "nested"
    nested.mkdir()
    source = nested / "module.py"
    source.write_text("safe = True\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "module.py").write_text("secret = 'must not be read'\n", encoding="utf-8")

    probe = tmp_path / "symlink-probe"
    try:
        probe.symlink_to(outside, target_is_directory=True)
        probe.unlink()
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlink creation is not available on this platform")

    if not (
        os.name == "posix"
        and getattr(os, "O_NOFOLLOW", 0)
        and getattr(os, "O_DIRECTORY", 0)
        and os.open in getattr(os, "supports_dir_fd", set())
    ):
        pytest.skip("Descriptor-relative no-follow traversal is not supported")

    original_open = os.open
    swapped = False

    def swap_directory_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "nested" and kwargs.get("dir_fd") is not None and not swapped:
            nested.rename(tmp_path / "nested-original")
            nested.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(scanner.os, "open", swap_directory_then_open)
    result = scanner._safe_text(source, 1024, root=tmp_path)

    assert swapped is True
    assert result is None
