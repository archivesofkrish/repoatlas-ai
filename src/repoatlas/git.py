"""Safe Git metadata helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def get_revision(root: Path) -> str | None:
    """Return the current Git commit without invoking repository hooks or config."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
            env={
                "PATH": "/usr/bin:/bin",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
        value = result.stdout.strip()
        return (
            value
            if len(value) == 40 and all(char in "0123456789abcdef" for char in value)
            else None
        )
    except (OSError, subprocess.SubprocessError):
        return None
