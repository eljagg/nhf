"""The client's real address, trusting only the proxies we run behind.

X-Forwarded-For is a list that every proxy appends to; anything to the left of our own proxies' entries was written
by the client and can be forged. With TRUSTED_PROXY_COUNT = N we take the N-th entry from the right (Railway's edge
or NHF's load balancer adds one), check it is a real IP address, and otherwise fall back to REMOTE_ADDR.
"""

import ipaddress

from django.conf import settings


def _valid(value):
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(request):
    if request is None:
        return None
    remote = _valid(request.META.get("REMOTE_ADDR", "") or "")
    count = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if count:
        hops = [h for h in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if h.strip()]
        if len(hops) >= count:
            return _valid(hops[-count]) or remote
    return remote
