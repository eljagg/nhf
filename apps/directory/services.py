"""Directory sync."""

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.core import audit

from . import ldap
from .provisioning import NotAuthorised, provision


def sync_ad_users():
    """For every AD-sourced account: still in AD, still enabled, still in a mapped group? Otherwise disable it and end its sessions."""
    if not settings.LDAP["ENABLED"]:
        return {"skipped": True}
    from apps.security.services import end_sessions

    result = {"checked": 0, "disabled": 0, "updated": 0}
    system = get_user_model().objects.filter(is_superuser=True, is_active=True).first()
    for user in get_user_model().objects.filter(source="ad", is_active=True):
        result["checked"] += 1
        identity = ldap.lookup(user.username)
        reason = None
        if identity is None:
            reason = "no longer in the directory"
        else:
            try:
                provision(identity)
                result["updated"] += 1
            except NotAuthorised as exc:
                reason = str(exc)
        if reason:
            type(user).objects.filter(pk=user.pk).update(is_active=False)
            if system:
                end_sessions(user, by=system, reason="disabled by directory sync")
            audit.record("directory.user_disabled", user, f"{user.username} disabled by directory sync: {reason}")
            result["disabled"] += 1
    return result
