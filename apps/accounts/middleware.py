"""Session idle timeout and MFA enforcement."""

import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .roles import has_role

# Reachable before the second factor is verified. Everything else under /accounts/ (my account, temporary roles,
# password change) needs MFA like any other page.
OPEN_PATHS = ("/accounts/login/", "/accounts/logout/", "/accounts/mfa/", "/accounts/password/reset/", "/static/", "/healthz", "/api/intake/")


class SessionIdleMiddleware:
    """Log the user out after SESSION_IDLE_MINUTES without a request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = int(time.time())
            last = request.session.get("last_seen", now)
            if now - last > settings.SESSION_IDLE_MINUTES * 60:
                logout(request)
                return redirect(f"{reverse('accounts:login')}?idle=1")
            if now - last > 30:
                request.session["last_seen"] = now
            request.session.setdefault("last_seen", now)
        return self.get_response(request)


class MFAEnforcementMiddleware:
    """Users in MFA-required roles must verify a TOTP device before reaching the application (UM10004)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and not request.path.startswith(OPEN_PATHS):
            needs = settings.MFA_REQUIRED or has_role(user, *settings.MFA_REQUIRED_ROLES)
            if needs and not user.is_verified():
                from django_otp import devices_for_user

                if any(True for _ in devices_for_user(user, confirmed=True)):
                    return redirect(f"{reverse('accounts:mfa-verify')}?next={request.path}")
                return redirect(reverse("accounts:mfa-setup"))
        return self.get_response(request)
