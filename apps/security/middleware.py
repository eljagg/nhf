"""Access logging (every request by a signed-in user), session last-seen, and password expiry."""

import logging
import time
from datetime import timedelta

from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Parameter

from .models import AccessLog, UserSession
from .signals import client_ip, session_ref

log = logging.getLogger(__name__)

SKIP_PREFIXES = ("/static/", "/healthz", "/favicon")
OBJECT_KWARGS = {"tracking": "application", "member_number": "member", "mcj": "doctor", "tracking_number": "application"}
PASSWORD_EXEMPT = ("/accounts/login/", "/accounts/logout/", "/accounts/mfa/", "/accounts/password/", "/static/", "/healthz", "/api/intake/", "/how-to-apply/")


def _skip(request):
    path = request.path
    return path.startswith(SKIP_PREFIXES) or path.endswith("/heartbeat/") or request.GET.get("poll")


class AccessLogMiddleware:
    """Writes one AccessLog row per request by a signed-in user (polling and static files excluded)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or _skip(request):
            return response
        match = getattr(request, "resolver_match", None)
        object_type = object_ref = ""
        if match:
            for kwarg, kind in OBJECT_KWARGS.items():
                if kwarg in match.kwargs:
                    object_type, object_ref = kind, str(match.kwargs[kwarg])[:40]
                    break
        try:
            key = request.session.session_key
            AccessLog.objects.create(
                user=user,
                session_ref=session_ref(key),
                method=request.method[:8],
                path=request.get_full_path()[:300],
                route=(match.view_name if match else "")[:80],
                status=response.status_code,
                duration_ms=int((time.monotonic() - started) * 1000),
                ip_address=client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:200],
                object_type=object_type,
                object_ref=object_ref,
            )
            if key and cache.add(f"seen:{key}", 1, 60):  # last-seen at most once a minute per session
                UserSession.objects.filter(session_key=key).update(last_seen=timezone.now())
            if object_type == "member" and request.method == "GET" and response.status_code == 200:
                from .services import check_bulk_viewing

                check_bulk_viewing(user)
        except Exception:  # noqa: BLE001 - logging must never break the request
            log.exception("access log write failed for %s", request.path)
        return response


class PasswordExpiryMiddleware:
    """Staff whose password is older than the configured age are sent to change it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(PASSWORD_EXEMPT):
            days = int(Parameter.get("password-max-age-days") or 0)
            changed = getattr(user, "password_changed_at", None)
            if days and changed and timezone.now() - changed > timedelta(days=days):
                messages.warning(request, f"Your password is more than {days} days old. Choose a new one to continue.")
                return redirect(reverse("accounts:password-change"))
        return self.get_response(request)
