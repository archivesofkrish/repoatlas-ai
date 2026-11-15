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
