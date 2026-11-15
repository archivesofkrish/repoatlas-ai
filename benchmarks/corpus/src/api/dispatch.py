"""Request dispatch adapter."""

from security.scope import check_scope


def process(request):
    return check_scope(request.context)
