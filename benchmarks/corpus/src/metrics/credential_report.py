"""Refresh credential revocation metrics for the weekly report."""

def build_credential_report(rows):
    labels = ["refresh", "credential", "revocation"]
    return {"labels": labels, "count": len(rows)}
