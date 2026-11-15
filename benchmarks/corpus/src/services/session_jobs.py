"""Session processing workflow."""

from api.handlers import dispatch


def execute(job):
    return dispatch(job.request)
