"""Safe, bounded repository file discovery.

The scanner reads regular text files only. It never executes repository code and does not
follow symlinks. Limits and exclusions are explicit so untrusted repositories cannot cause
unbounded ingestion work.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from repoatlas.models import RepositoryFile, normalized_relative_path

DEFAULT_IGNORES = {
    ".git", ".hg", ".svn", ".venv", "venv", "__pycache__", "node_modules",
    "dist", "build", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".tox", "coverage", "site-packages",
}
SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.yml", "secrets.yaml", "service-account.json",
}
SENSITIVE_DIRECTORIES = {".aws", ".ssh", ".gnupg", ".azure", ".config/gcloud"}
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


def _safe_text(path: Path, max_file_bytes: int) -> tuple[bytes, str] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_file_bytes:
            return None
        with path.open("rb") as stream:
            data = stream.read(max_file_bytes + 1)
        if len(data) > max_file_bytes or _is_binary(data[:8192]):
            return None
        text = data.decode("utf-8")
        return data, text
    except (OSError, UnicodeDecodeError):
        return None


def scan_files(
    root: str | Path,
    *,
    max_files: int = 20_000,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 100_000_000,
    extra_ignores: set[str] | None = None,
) -> tuple[list[RepositoryFile], dict[str, int], list[str]]:
    """Discover bounded text files without following symlinks."""
    base = Path(root).expanduser().resolve(strict=True)
    if not base.is_dir():
        raise ScanError(f"Repository path is not a directory: {base}")
    if max_files < 1 or max_file_bytes < 1 or max_total_bytes < 1:
        raise ScanError("All scan limits must be positive integers")

    ignores = DEFAULT_IGNORES | (extra_ignores or set())
    files: list[RepositoryFile] = []
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
                name.lower() in {".aws", ".ssh", ".gnupg"}
                or relative_directory == ".config/gcloud"
                or relative_directory.startswith(".config/gcloud/")
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
                return files, excluded, warnings
            result = _safe_text(path, max_file_bytes)
            if result is None:
                excluded["binary_or_unreadable"] += 1
                continue
            data, text = result
            files.append(RepositoryFile(
                path=rel, language=language, size_bytes=len(data),
                line_count=len(text.splitlines()), sha256=hashlib.sha256(data).hexdigest(),
            ))
            total_bytes += len(data)
            if len(files) >= max_files:
                warnings.append(f"File-count limit ({max_files}) reached; scan is partial.")
                return files, excluded, warnings
    return files, excluded, warnings
