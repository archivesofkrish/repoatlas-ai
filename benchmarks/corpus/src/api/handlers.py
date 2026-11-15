"""Request handler adapter."""

from security.claims import allowed


def dispatch(request):
    return allowed(request.context)
