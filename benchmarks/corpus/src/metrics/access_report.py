"""Role permission authorization reporting for access reviews."""

def build_access_report(rows):
    labels = ["role", "permission", "authorization"]
    return {"labels": labels, "count": len(rows)}
