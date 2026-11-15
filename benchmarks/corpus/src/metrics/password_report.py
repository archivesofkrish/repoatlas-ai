"""Reporting-only summaries; this module does not enforce account policy."""

def build_password_history_report(rows):
    """Summarise password history enforcement account registration metrics."""
    labels = ["password", "history", "enforcement", "account", "registration"]
    return {"labels": labels, "rows": len(rows)}
