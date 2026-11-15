from pathlib import Path

import pytest

from repoatlas.guardrails import (
    evaluate_architecture_policy, load_architecture_policy,
    render_architecture_guardrails_html,
)


def report():
    return {
        "repository": "sample", "revision": "abc123", "snapshot_id": "snapshot",
        "packages": [
            {"name": "api", "cross_package_imports": 4},
            {"name": "application", "cross_package_imports": 2},
            {"name": "database", "cross_package_imports": 0},
        ],
        "package_dependencies": [
            {"source": "api", "target": "application", "edge_count": 3},
            {"source": "api", "target": "database", "edge_count": 1},
            {"source": "application", "target": "database", "edge_count": 2},
        ],
        "files": [
            {"path": "api/routes.py", "package": "api",
             "dependencies": ["application/service.py", "database/session.py"]},
            {"path": "application/service.py", "package": "application",
             "dependencies": ["database/session.py"]},
        ],
        "cycles": [["database/a.py", "database/b.py"]], "total_cycles": 1,
    }


def test_policy_detects_forbidden_disallowed_capped_and_cyclic_dependencies():
    result = evaluate_architecture_policy(
        report(),
        {
            "schema_version": 1, "name": "Layering policy",
            "allowed_package_dependencies": {"api": ["application"], "application": []},
            "forbidden_package_dependencies": [
                {"source": "api", "target": "database", "reason": "API must not access storage."}
            ],
            "max_cross_package_imports": {"api": 3}, "fail_on_cycles": True,
        },
    )
    assert result["status"] == "FAIL"
    assert result["summary"]["violations"] == 4
    assert result["summary"]["critical"] == 1
    assert result["summary"]["high"] == 2
    assert result["summary"]["medium"] == 1
    forbidden = next(x for x in result["violations"] if x["rule"] == "forbidden_package_dependency")
    assert forbidden["evidence"] == [{
        "source_file": "api/routes.py", "target_file": "database/session.py"
    }]


def test_policy_passes_when_observed_dependencies_satisfy_rules():
    sample = report()
    sample["package_dependencies"] = [{"source": "api", "target": "application", "edge_count": 3}]
    sample["packages"] = [{"name": "api", "cross_package_imports": 3}]
    sample["cycles"] = []
    sample["total_cycles"] = 0
    result = evaluate_architecture_policy(
        sample,
        {"schema_version": 1, "allowed_package_dependencies": {"api": ["application"]},
         "max_cross_package_imports": {"api": 3}, "fail_on_cycles": True},
    )
    assert result["status"] == "PASS"
    assert result["summary"]["violations"] == 0


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({"schema_version": 2, "fail_on_cycles": True}, "schema_version"),
        ({"schema_version": 1, "allowed_package_dependecies": {}}, "unknown keys"),
        ({"schema_version": 1, "allowed_package_dependencies": {"api": "database"}}, "array"),
        ({"schema_version": 1, "max_cross_package_imports": {"api": True}}, "non-negative integer"),
        ({"schema_version": 1, "fail_on_cycles": "yes"}, "boolean"),
        ({"schema_version": 1}, "at least one active rule"),
    ],
)
def test_policy_rejects_invalid_or_misspelled_rules(policy, message):
    with pytest.raises(ValueError, match=message):
        evaluate_architecture_policy(report(), policy)


def test_policy_loader_rejects_non_object_and_oversized_files(tmp_path: Path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_architecture_policy(invalid)
    oversized = tmp_path / "large.json"
    oversized.write_bytes(b" " * 65_537)
    with pytest.raises(ValueError, match="byte limit"):
        load_architecture_policy(oversized)


def test_guardrails_html_escapes_untrusted_values(tmp_path: Path):
    result = evaluate_architecture_policy(
        report(),
        {"schema_version": 1, "name": "Safe rendering",
         "forbidden_package_dependencies": [
             {"source": "api", "target": "database",
              "reason": "</h2><script>alert(1)</script>"}
         ]},
    )
    result["repository"] = "</title><script>bad()</script>"
    document = render_architecture_guardrails_html(result, tmp_path / "policy.html").read_text()
    assert "<!doctype html>" in document
    assert "cdn" not in document.lower()
    assert "&lt;/title&gt;&lt;script&gt;bad()&lt;/script&gt;" in document
    assert "&lt;/h2&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in document
