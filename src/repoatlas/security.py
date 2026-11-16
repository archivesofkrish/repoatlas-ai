"""Conservative secret-pattern detection and redaction for retrieved evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    (
        "generic_assignment",
        re.compile(
            r"""(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['"]?"""
            r"""([A-Za-z0-9_./+=-]{12,})['"]?"""
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SecretFinding:
    kind: str
    start: int
    end: int


def detect_secrets(text: str) -> list[SecretFinding]:
    """Detect common credential shapes; this is a heuristic, not a guarantee."""
    findings = []
    for kind, pattern in PATTERNS:
        findings.extend(
            SecretFinding(kind, match.start(), match.end())
            for match in pattern.finditer(text)
        )
    return sorted(findings, key=lambda item: (item.start, item.end))


def _coalesce_overlapping_findings(
    findings: list[SecretFinding],
) -> list[SecretFinding]:
    """Merge overlapping spans before replacements can shift later offsets.

    Multiple detectors commonly match the same credential (for example, both
    generic_assignment and aws_access_key). Replacing those matches one by one
    from right to left is unsafe because an earlier replacement can change
    the offsets of another overlapping span. A single merged replacement
    avoids leaving fragments of the original assignment or secret.
    """
    merged: list[SecretFinding] = []
    kinds_by_group: list[set[str]] = []

    for finding in sorted(findings, key=lambda item: (item.start, item.end)):
        if merged and finding.start < merged[-1].end:
            previous = merged[-1]
            merged[-1] = SecretFinding(
                kind=previous.kind,
                start=previous.start,
                end=max(previous.end, finding.end),
            )
            kinds_by_group[-1].add(finding.kind)
        else:
            merged.append(finding)
            kinds_by_group.append({finding.kind})

    return [
        SecretFinding(
            kind="+".join(sorted(kinds)),
            start=finding.start,
            end=finding.end,
        )
        for finding, kinds in zip(merged, kinds_by_group, strict=True)
    ]


def redact_secrets(text: str) -> str:
    """Redact detected credential-like spans without changing other text."""
    findings = _coalesce_overlapping_findings(detect_secrets(text))
    for finding in reversed(findings):
        text = text[:finding.start] + f"[REDACTED:{finding.kind}]" + text[finding.end:]
    return text
