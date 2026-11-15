"""Task execution entry point."""

from api.dispatch import process


def execute(task):
    return process(task.request)
