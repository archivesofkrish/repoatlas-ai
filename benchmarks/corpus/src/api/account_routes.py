"""Account registration route."""

from security.password_policy import enforce_password_history


def submit(payload):
    password = payload.get("password", "")
    history = payload.get("history", [])
    return enforce_password_history(password, history)
