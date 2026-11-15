"""Administrative task entry point."""

from api.commands import run


def execute(job):
    return run(job.command)
