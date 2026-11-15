"""Session processing workflow."""

from api.handlers import dispatch


def refresh(job):
    return dispatch(job.request)
