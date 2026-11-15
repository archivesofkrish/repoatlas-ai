"""Tenant isolation boundary reporting for monthly operational reviews."""

def build_scope_report(rows):
    labels = ["tenant", "isolation", "boundary"]
    return {"labels": labels, "count": len(rows)}
