"""Session idle timeout and MFA enforcement."""

import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .roles import has_role

# Reachable before the second factor is verified. Everything else under /accounts/ (my account, temporary roles,
# password change) needs MFA like any other page.
OPEN_PATHS = ("/accounts/login/", "/accounts/logout/", "/accounts/mfa/", "/accounts/oidc/", "/accounts/password/reset/", "/static/", "/healthz", "/api/intake/")


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


def mfa_required_for(user):
    """Every staff account needs a second factor; the demo-only switch narrows it to the privileged roles."""
    if has_role(user, *settings.MFA_REQUIRED_ROLES):
        return True
    if settings.DEMO_MODE and settings.MFA_DEMO_PRIVILEGED_ONLY:
        return False
    return settings.MFA_REQUIRED


def mfa_satisfied(request):
    """A verified TOTP/backup code this session, or Entra ID reporting that it performed MFA at sign-in."""
    return request.user.is_verified() or bool(request.session.get("idp_mfa"))


class MFAEnforcementMiddleware:
    """Staff must verify a second factor before reaching the application (UM10004)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and getattr(user, "is_suspended", False) and not request.path.startswith(("/static/", "/healthz")):
            from django.contrib.auth import logout

            logout(request)  # a suspension takes effect on the next request, wherever the person is signed in
            return redirect(f"{reverse('accounts:login')}?suspended=1")
        if user.is_authenticated and not request.path.startswith(OPEN_PATHS):
            if mfa_required_for(user) and not mfa_satisfied(request):
                from django_otp.plugins.otp_totp.models import TOTPDevice

                if TOTPDevice.objects.filter(user=user, confirmed=True).exists():
                    return redirect(f"{reverse('accounts:mfa-verify')}?next={request.path}")
                return redirect(reverse("accounts:mfa-setup"))
        return self.get_response(request)
