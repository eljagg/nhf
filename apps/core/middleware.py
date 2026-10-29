"""Request id and current-user binding."""

import uuid

from . import audit


class RequestIDMiddleware:
    """Attach a request id (from X-Request-ID or new) to every request and response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-ID", "")[:40] or uuid.uuid4().hex
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response


class CurrentUserMiddleware:
    """Bind the request for audit helpers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = audit.set_request(request)
        try:
            return self.get_response(request)
        finally:
            audit.reset_request(token)
