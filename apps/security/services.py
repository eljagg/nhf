"""Security alert rules and session control."""

from datetime import timedelta
from importlib import import_module

from django.conf import settings
from django.utils import timezone

from apps.core import audit
from apps.core.models import Parameter

from .models import AccessLog, SecurityAlert, UserSession


def raise_alert(kind, message, *, severity="medium", user=None, subject="", dedupe_minutes=60, **data):
    """Create an alert unless the same kind for the same subject was raised recently; notify admins and managers."""
    since = timezone.now() - timedelta(minutes=dedupe_minutes)
    key = subject or (user.username if user else "")
    if SecurityAlert.objects.filter(kind=kind, subject=key, at__gte=since).exists():
        return None
    alert = SecurityAlert.objects.create(kind=kind, severity=severity, user=user, subject=key, message=message[:400], data=data)
    audit.record("security.alert", alert, message)
    from apps.core.notifications import notify_role

    for role in ("ict_admin", "manager"):
        notify_role(role, "security-alert", obj=alert, link="/security/", message=message)
    return alert


def check_bulk_viewing(user):
    """Many distinct member profiles opened by one user within an hour."""
    limit = int(Parameter.get("alert-bulk-view-per-hour"))
    since = timezone.now() - timedelta(hours=1)
    seen = AccessLog.objects.filter(user=user, object_type="member", at__gte=since).values("object_ref").distinct().count()
    if seen > limit:
        raise_alert("bulk_viewing", f"{user.username} opened {seen} member records in the last hour (limit {limit}).", severity="high", user=user, count=seen)


def check_trn_failures(user):
    """Many invalid or mismatched TRN checks by one user within an hour."""
    from apps.identity.models import TrnValidation

    if user is None:
        return
    limit = int(Parameter.get("alert-failed-trn-per-hour"))
    since = timezone.now() - timedelta(hours=1)
    qs = TrnValidation.objects.filter(requested_by=user, created_at__gte=since).exclude(purpose="screen")
    failed = qs.filter(status="invalid").count() + qs.filter(match_result="mismatch").count()
    if failed > limit:
        raise_alert("trn_failures", f"{user.username} had {failed} invalid or mismatched TRN checks in the last hour (limit {limit}).", user=user, count=failed)


def end_sessions(user, *, by, reason="ended by administrator", keep_key=None):
    """End every open session of a user (except keep_key): the session is deleted, so the next request signs them out."""
    store = import_module(settings.SESSION_ENGINE).SessionStore
    ended = 0
    for s in UserSession.objects.filter(user=user, ended_at__isnull=True):
        if keep_key and s.session_key == keep_key:
            continue
        store(session_key=s.session_key).delete()
        s.ended_at = timezone.now()
        s.end_reason = reason
        s.save(update_fields=["ended_at", "end_reason"])
        ended += 1
    audit.record("security.sessions_ended", user, f"{ended} session(s) of {user.username} ended by {by.username}", actor=by, reason=reason)
    return ended


def active_sessions(user=None):
    """Sessions that have not ended and were used within the absolute session lifetime."""
    since = timezone.now() - timedelta(seconds=settings.SESSION_COOKIE_AGE)
    qs = UserSession.objects.filter(ended_at__isnull=True, last_seen__gte=since).select_related("user")
    return qs.filter(user=user) if user else qs
