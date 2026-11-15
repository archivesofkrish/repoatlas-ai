"""Conservative secret-pattern detection and redaction for retrieved evidence."""
from __future__ import annotations
import re
from dataclasses import dataclass

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("generic_assignment", re.compile(r"""(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['"]?([A-Za-z0-9_./+=-]{12,})""")),
)

@dataclass(frozen=True, slots=True)
class SecretFinding:
    kind: str
    start: int
    end: int

def detect_secrets(text: str) -> list[SecretFinding]:
    findings = []
    for kind, pattern in PATTERNS:
        findings.extend(SecretFinding(kind, match.start(), match.end()) for match in pattern.finditer(text))
    return sorted(findings, key=lambda item: item.start)

def redact_secrets(text: str) -> str:
    for finding in reversed(detect_secrets(text)):
        text = text[:finding.start] + f"[REDACTED:{finding.kind}]" + text[finding.end:]
    return text
