"""Tenant isolation boundary for requests entering a workspace."""

def check_scope(context):
    return context.get("workspace_id") is not None
