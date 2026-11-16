from repoatlas.security import detect_secrets, redact_secrets


def test_redacts_common_token_patterns():
    text = "token = 'ghp_abcdefghijklmnopqrstuvwxyz123456'"
    assert detect_secrets(text)
    redacted = redact_secrets(text)
    assert "ghp_" not in redacted
    assert "REDACTED" in redacted


def test_does_not_change_normal_text():
    text = "The access token is validated by the middleware."
    assert redact_secrets(text) == text


def test_overlapping_assignment_and_github_token_matches_are_replaced_once():
    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    redacted = redact_secrets(f"prefix token='{secret}' suffix")

    assert redacted == (
        "prefix [REDACTED:generic_assignment+github_token] suffix"
    )
    assert secret not in redacted
    assert "ghp_" not in redacted


def test_overlapping_assignment_and_aws_key_matches_leave_no_offset_fragment():
    secret = "AKIAABCDEFGHIJKLMNOP"
    redacted = redact_secrets(f'before api_key="{secret}" after')

    assert redacted == (
        "before [REDACTED:aws_access_key+generic_assignment] after"
    )
    assert secret not in redacted
    assert "_key" not in redacted


def test_multiple_overlapping_findings_preserve_surrounding_text():
    text = (
        "left token='ghp_abcdefghijklmnopqrstuvwxyz123456' middle "
        "password='supersecretvalue123' right"
    )
    redacted = redact_secrets(text)

    assert redacted.startswith("left ")
    assert redacted.endswith(" right")
    assert "ghp_" not in redacted
    assert "supersecretvalue123" not in redacted
    assert redacted.count("[REDACTED:") == 2
