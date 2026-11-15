"""Role permission authorization rules for protected operations."""

def may_proceed(context):
    return context.get("permitted") is True
