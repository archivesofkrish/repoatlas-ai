"""Command adapter."""

from security.rules import may_proceed


def run(command):
    return may_proceed(command.context)
