from pathlib import Path

import pytest
from fastapi import HTTPException

from repoatlas.api_validation import bounded_integer, bounded_weight, resolve_workspace_path


@pytest.mark.parametrize("value", [True, False, 1.5, "3", 0, 21])
def test_bounded_integer_rejects_non_integer_and_out_of_range(value):
    with pytest.raises(HTTPException) as error:
        bounded_integer(value, minimum=1, maximum=20, field="top_k")
    assert error.value.status_code == 422


def test_bounded_integer_accepts_inclusive_bounds():
    assert bounded_integer(1, minimum=1, maximum=20, field="top_k") == 1
    assert bounded_integer(20, minimum=1, maximum=20, field="top_k") == 20


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, "0.5"])
def test_bounded_weight_rejects_non_finite_and_non_numeric_values(value):
    with pytest.raises(HTTPException):
        bounded_weight(value, minimum=0.1, maximum=0.9, field="lexical_weight")


def test_bounded_weight_accepts_finite_boundary_values():
    assert bounded_weight(0.1, minimum=0.1, maximum=0.9, field="weight") == 0.1
    assert bounded_weight(0.9, minimum=0.1, maximum=0.9, field="weight") == 0.9


def test_resolve_workspace_path_rejects_escape_and_accepts_child(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    child = root / "project"
    child.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    assert resolve_workspace_path(root.resolve(), "project") == child.resolve()
    with pytest.raises(HTTPException) as error:
        resolve_workspace_path(root.resolve(), "../outside")
    assert error.value.status_code == 400
