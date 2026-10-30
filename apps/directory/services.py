"""Keep directory accounts in step with Active Directory: nightly/hourly sync and in-session re-checks."""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core import audit

from . import ldap
from .provisioning import NotAuthorised, provision

log = logging.getLogger(__name__)


def disable(user, reason, *, by=None):
    """Directory says this person no longer has access: deactivate here and end every session."""
    from apps.security.services import end_sessions

    get_user_model().objects.filter(pk=user.pk).update(is_active=False, deactivated_at=timezone.now(), deactivated_by_directory=True)
    actor = by or get_user_model().objects.filter(is_superuser=True, is_active=True).first() or user
    end_sessions(user, by=actor, reason="disabled in the directory")
    audit.record("directory.user_disabled", user, f"{user.username} disabled because the directory account is {reason}")


def assess(user):
    """Ask AD about one account without disabling anything: ("ok", "") with roles refreshed, ("remove", reason) or ("unreachable", reason)."""
    try:
        identity = ldap.lookup(user.username)
    except ldap.DirectoryError as exc:
        log.warning("directory check of %s skipped: %s", user.username, exc)
        return "unreachable", str(exc)
    if identity is None:
        return "remove", "no longer in the directory"
    if not identity.enabled:
        return "remove", "disabled in the directory"
    try:
        provision(identity)
    except NotAuthorised:
        return "remove", "no longer in a group that gives access"
    return "ok", ""


def recheck(user):
    """In-session check of one account. True = still allowed; False = access removed (account disabled); None = directory unreachable."""
    outcome, reason = assess(user)
    if outcome == "remove":
        disable(user, reason)
        return False
    return True if outcome == "ok" else None


def sync_ad_users():
    """Hourly: every active AD account still in AD, enabled and in a mapped group? Disable those that are not.

    Safety stop: if the run would disable more than 5% of directory accounts (minimum 3), nothing is disabled and a
    high alert is raised instead — that pattern means a directory misconfiguration, not a wave of leavers.
    """
    if not settings.LDAP["ENABLED"]:
        return {"skipped": True}
    users = list(get_user_model().objects.filter(source="ad", is_active=True))
    result = {"checked": 0, "disabled": 0, "updated": 0, "unreachable": 0, "held": 0}
    removals = []
    for user in users:
        result["checked"] += 1
        outcome, reason = assess(user)
        if outcome == "unreachable":
            result["unreachable"] += 1
            return result  # directory down: try again next run
        if outcome == "remove":
            removals.append((user, reason))
        else:
            result["updated"] += 1
    if len(removals) > max(3, len(users) * 0.05):
        from apps.security.services import raise_alert

        result["held"] = len(removals)
        raise_alert(
            "directory",
            f"Directory sync would have disabled {len(removals)} of {len(users)} accounts; nothing was disabled. Check the directory settings and group mappings.",
            severity="high",
            subject="directory-sync",
        )
        return result
    for user, reason in removals:
        disable(user, reason)
        result["disabled"] += 1
    return result
