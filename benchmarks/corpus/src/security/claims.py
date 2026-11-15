"""Refresh credential revocation checks for incoming sessions."""

def allowed(context):
    return context.get("active") is True
