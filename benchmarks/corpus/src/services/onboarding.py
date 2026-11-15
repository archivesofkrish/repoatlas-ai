"""Workflow orchestration entry point."""

from api.account_routes import submit


def begin(payload):
    return submit(payload)
