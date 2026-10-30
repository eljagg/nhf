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


class SecurityHeadersMiddleware:
    """Headers Django does not set itself, and a cap on request bodies before they are read."""

    PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), interest-cohort=()"

    def __init__(self, get_response):
        self.get_response = get_response
        from django.conf import settings

        self.max_bytes = getattr(settings, "MAX_REQUEST_BYTES", 25 * 1024 * 1024)

    def __call__(self, request):
        try:
            length = int(request.META.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length > self.max_bytes:
            from django.http import HttpResponse

            return HttpResponse("Request too large.", status=413, content_type="text/plain")
        response = self.get_response(request)
        response.setdefault("Permissions-Policy", self.PERMISSIONS_POLICY)
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        if request.user.is_authenticated if hasattr(request, "user") else False:
            response.setdefault("Cache-Control", "no-store, private")  # staff pages hold personal data: never cached by browsers or proxies
        return response
