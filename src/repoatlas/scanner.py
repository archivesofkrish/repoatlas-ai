"""Safe, bounded repository file discovery.

The scanner reads regular text files only. It never executes repository code and does not
follow symlinks. Limits and exclusions are explicit so untrusted repositories cannot cause
unbounded ingestion work.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from repoatlas.models import (
    RepositoryFile,
    RepositorySnapshot,
    SourceDocument,
    normalized_relative_path,
)
from repoatlas.git import get_revision

DEFAULT_IGNORES = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".tox", "coverage", "site-packages",
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.yml", "secrets.yaml", "service-account.json",
    ".git-credentials", ".netrc", ".npmrc", ".pypirc", ".dockercfg",
    "credentials.db", "secrets.json", "client_secret.json",
}
# Exclude credential stores by location before opening candidate files.
# Many CLI stores use ordinary YAML/JSON filenames, so filename heuristics alone
# are insufficient.
SENSITIVE_DIRECTORY_NAMES = {
    ".aws", ".ssh", ".gnupg", ".azure", ".docker", ".kube",
}
SENSITIVE_DIRECTORY_PATHS = {
    ".config/gcloud", ".config/gh", ".config/hub",
}
TEXT_EXTENSIONS = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".cjs": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C/C++",
    ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala", ".sh": "Shell",
    ".bash": "Shell", ".sql": "SQL", ".html": "HTML", ".css": "CSS",
    ".scss": "SCSS", ".json": "JSON", ".toml": "TOML", ".yaml": "YAML",
    ".yml": "YAML", ".xml": "XML", ".md": "Markdown", ".rst": "reStructuredText",
    ".txt": "Text", ".ini": "INI", ".cfg": "INI", ".conf": "Config",
    ".dockerfile": "Dockerfile", ".tf": "Terraform", ".graphql": "GraphQL",
    ".proto": "Protocol Buffers", ".ipynb": "Jupyter Notebook",
}
TEXT_NAMES = {"dockerfile": "Dockerfile", "makefile": "Makefile", "justfile": "Justfile"}


class ScanError(ValueError):
    """Raised when repository input is invalid or unsafe."""


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def _open_scanned_file(path: Path, root: Path | None) -> int:
    """Open a regular file without following symlink path components where supported.

    POSIX dir-fd traversal pins each parent directory and applies O_NOFOLLOW to
    every component. Other platforms use a final-component no-follow flag when
    available, followed by lstat/fstat identity checks in _safe_text.
    """
    read_only = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)

    if (
        root is not None
        and os.name == "posix"
        and no_follow
        and directory_flag
        and os.open in getattr(os, "supports_dir_fd", set())
    ):
        relative = path.relative_to(root)
        if not relative.parts:
            raise OSError("A repository directory is not a source file")

        root_fd = os.open(root, read_only | directory_flag | no_follow)
        current_fd = root_fd
        try:
            for component in relative.parts[:-1]:
                next_fd = os.open(
                    component,
                    read_only | directory_flag | no_follow,
                    dir_fd=current_fd,
                )
                if current_fd != root_fd:
                    os.close(current_fd)
                current_fd = next_fd
            return os.open(
                relative.parts[-1],
                read_only | no_follow,
                dir_fd=current_fd,
            )
        finally:
            if current_fd != root_fd:
                os.close(current_fd)
            os.close(root_fd)

    return os.open(path, read_only | no_follow)


def _same_open_file(path: Path, opened_stat: os.stat_result) -> bool:
    """Best-effort path identity check for platforms without O_NOFOLLOW."""
    try:
        current = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        return False
    return (
        current.st_dev == opened_stat.st_dev
        and current.st_ino == opened_stat.st_ino
    )


def _safe_text(
    path: Path, max_file_bytes: int, *, root: Path | None = None
) -> tuple[bytes, str] | None:
    descriptor: int | None = None
    try:
        descriptor = _open_scanned_file(path, root)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            return None
        if opened_stat.st_size > max_file_bytes:
            return None

        if not getattr(os, "O_NOFOLLOW", 0) and not _same_open_file(path, opened_stat):
            return None

        stream = os.fdopen(descriptor, "rb", closefd=True)
        descriptor = None
        with stream:
            data = stream.read(max_file_bytes + 1)

        if not getattr(os, "O_NOFOLLOW", 0) and not _same_open_file(path, opened_stat):
            return None
        if len(data) > max_file_bytes or _is_binary(data[:8192]):
            return None
        text = data.decode("utf-8")
        return data, text
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _scan_files(
    root: str | Path,
    *,
    max_files: int = 20_000,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 100_000_000,
    extra_ignores: set[str] | None = None,
    retain_content: bool,
) -> tuple[list[RepositoryFile], list[SourceDocument], dict[str, int], list[str]]:
    """Discover bounded text files without following symlinks."""
    base = Path(root).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise ScanError(f"Repository path is not a directory: {base}")
    if max_files < 1 or max_file_bytes < 1 or max_total_bytes < 1:
        raise ScanError("All scan limits must be positive integers")

    ignores = DEFAULT_IGNORES | (extra_ignores or set())
    files: list[RepositoryFile] = []
    documents: list[SourceDocument] = []
    excluded = {"ignored": 0, "sensitive": 0, "binary_or_unreadable": 0,
                "oversized": 0, "unsupported": 0, "symlink": 0}
    warnings: list[str] = []
    total_bytes = 0

    for current, dirs, filenames in os.walk(base, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs = []
        for name in sorted(dirs):
            candidate = current_path / name
            relative_directory = normalized_relative_path(base, candidate).lower()
            sensitive_directory = (
                name.lower() in SENSITIVE_DIRECTORY_NAMES
                or any(
                    relative_directory == sensitive
                    or relative_directory.startswith(sensitive + "/")
                    for sensitive in SENSITIVE_DIRECTORY_PATHS
                )
            )
            if name in ignores or sensitive_directory or candidate.is_symlink():
                excluded["ignored" if not candidate.is_symlink() else "symlink"] += 1
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs

        for filename in sorted(filenames):
            path = current_path / filename
            rel = normalized_relative_path(base, path)
            lower_name = filename.lower()
            suffix = path.suffix.lower()
            is_sensitive = (
                lower_name in SENSITIVE_NAMES
                or lower_name == ".env"
                or lower_name.startswith(".env.")
            )
            if is_sensitive:
                excluded["sensitive"] += 1
                continue
            language = TEXT_NAMES.get(lower_name) or TEXT_EXTENSIONS.get(suffix)
            if not language:
                excluded["unsupported"] += 1
                continue
            if path.is_symlink():
                excluded["symlink"] += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                excluded["binary_or_unreadable"] += 1
                continue
            if size > max_file_bytes:
                excluded["oversized"] += 1
                continue
            if total_bytes + size > max_total_bytes:
                warnings.append(
                    "Total byte limit reached; remaining files were not scanned "
                    f"(at {rel})."
                )
                return files, documents, excluded, warnings
            result = _safe_text(path, max_file_bytes, root=base)
            if result is None:
                excluded["binary_or_unreadable"] += 1
                continue
            data, text = result
            metadata = RepositoryFile(
                path=rel, language=language, size_bytes=len(data),
                line_count=len(text.splitlines()), sha256=hashlib.sha256(data).hexdigest(),
            )
            files.append(metadata)
            if retain_content:
                documents.append(SourceDocument(metadata=metadata, content=text))
            total_bytes += len(data)
            if len(files) >= max_files:
                warnings.append(f"File-count limit ({max_files}) reached; scan is partial.")
                return files, documents, excluded, warnings
    return files, documents, excluded, warnings



def create_snapshot(
    root: str | Path,
    *,
    max_files: int = 20_000,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 100_000_000,
    extra_ignores: set[str] | None = None,
) -> RepositorySnapshot:
    """Capture bounded source text once for consistent analysis and retrieval."""
    base = Path(root).expanduser().resolve(strict=True)
    revision_before = get_revision(base)
    files, documents, excluded, warnings = _scan_files(
        base,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        extra_ignores=extra_ignores,
        retain_content=True,
    )
    revision_after = get_revision(base)
    revision = revision_before if revision_before == revision_after else None
    if revision_before != revision_after:
        warnings.append("Git HEAD changed during scan; revision is not stable for this snapshot.")

    fingerprint = hashlib.sha256()
    for item in files:
        fingerprint.update(item.path.encode("utf-8"))
        fingerprint.update(b"\0")
        fingerprint.update(item.sha256.encode("ascii"))
        fingerprint.update(b"\n")
    return RepositorySnapshot(
        root=str(base),
        snapshot_id=fingerprint.hexdigest(),
        revision=revision,
        documents=tuple(documents),
        excluded=tuple(sorted(excluded.items())),
        warnings=tuple(warnings),
    )


def scan_files(
    root: str | Path,
    *,
    max_files: int = 20_000,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 100_000_000,
    extra_ignores: set[str] | None = None,
) -> tuple[list[RepositoryFile], dict[str, int], list[str]]:
    """Return file metadata only, preserving the original scanner API."""
    files, _documents, excluded, warnings = _scan_files(
        root,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
        extra_ignores=extra_ignores,
        retain_content=False,
    )
    return files, excluded, warnings
