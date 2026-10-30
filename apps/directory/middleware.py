"""Re-check signed-in Active Directory users against AD every few minutes.

The sign-in check and the hourly sync already refuse disabled accounts; this closes the gap for someone who is
already signed in when ICT disables them in AD (a leaver, a compromised account). If AD cannot be reached the
session continues and the check is retried at the next interval, so a domain-controller outage does not stop
the counters.
"""

import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from apps.core.models import Parameter

SKIP = ("/static/", "/healthz", "/accounts/login/", "/accounts/logout/")


class DirectoryRecheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if settings.LDAP["ENABLED"] and user.is_authenticated and getattr(user, "source", "") == "ad" and not request.path.startswith(SKIP):
            interval = int(Parameter.get("directory-recheck-minutes")) * 60
            last = request.session.get("directory_checked_at", 0)
            if interval and time.time() - last > interval:
                from .services import recheck

                outcome = recheck(user)
                if outcome is False:
                    logout(request)
                    return redirect(f"{reverse('accounts:login')}?revoked=1")
                request.session["directory_checked_at"] = time.time()
        return self.get_response(request)
