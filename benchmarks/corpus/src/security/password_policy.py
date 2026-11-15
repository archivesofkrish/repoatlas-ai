"""Password history enforcement for account registration."""

def enforce_password_history(candidate_password, password_history):
    """Reject passwords that reuse an older account credential."""
    return candidate_password not in password_history
