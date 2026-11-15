"""Strict shared input validation for bounded repository API operations."""

from __future__ import annotations

import math
from pathlib import Path

from fastapi import HTTPException


def bounded_integer(value: int, *, minimum: int, maximum: int, field: str) -> int:
    """Validate integer bounds without accepting booleans as integers."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be an integer between {minimum} and {maximum}",
        )
    return value


def bounded_weight(value: float, *, minimum: float, maximum: float, field: str) -> float:
    """Reject NaN/infinity as well as values outside an inclusive interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=422, detail=f"{field} must be a finite number")
    numeric = float(value)
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be between {minimum} and {maximum}",
        )
    return numeric


def resolve_workspace_path(root: Path, raw: str) -> Path:
    """Resolve an existing directory without allowing workspace escape."""
    try:
        candidate = (root / raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Repository path does not exist or cannot be accessed",
        ) from exc
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Repository path escapes configured root",
        ) from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=400, detail="Repository path must be a directory")
    return candidate
