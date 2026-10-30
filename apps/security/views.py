"""Security dashboard and user activity tracking."""

import csv
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.roles import has_role, role_names, role_required, users_with_role
from apps.core import audit
from apps.core.models import AuditEvent, Parameter

from .models import AccessLog, SecurityAlert
from .services import active_sessions, end_sessions

VIEW_ROLES = ("ict_admin", "manager", "auditor")
CONTROL_ROLES = ("ict_admin", "manager")


@role_required(*VIEW_ROLES)
def dashboard(request):
    """Open alerts, sign-in failures, locked accounts, sessions, MFA and password status."""
    from axes.models import AccessAttempt

    now = timezone.now()
    day_ago = now - timedelta(hours=24)
    limit = settings.AXES_FAILURE_LIMIT
    locked = AccessAttempt.objects.filter(failures_since_start__gte=limit, attempt_time__gte=now - settings.AXES_COOLOFF_TIME).order_by("-attempt_time")
    user_model = get_user_model()
    mfa_rows = []
    for role in settings.MFA_REQUIRED_ROLES:
        holders = list(users_with_role(role))
        enrolled = sum(1 for u in holders if TOTPDevice.objects.filter(user=u, confirmed=True).exists())
        mfa_rows.append({"role": role, "holders": len(holders), "enrolled": enrolled})
    max_age = int(Parameter.get("password-max-age-days") or 0)
    expiring = expired = []
    if max_age:
        cutoff = now - timedelta(days=max_age)
        expired = list(user_model.objects.filter(is_active=True, password_changed_at__lt=cutoff).order_by("password_changed_at")[:20])
        expiring = list(user_model.objects.filter(is_active=True, password_changed_at__gte=cutoff, password_changed_at__lt=cutoff + timedelta(days=14))[:20])
    ctx = {
        "alerts": SecurityAlert.objects.filter(acknowledged_at__isnull=True).select_related("user")[:50],
        "recent_alerts": SecurityAlert.objects.filter(acknowledged_at__isnull=False).select_related("acknowledged_by")[:10],
        "failed_24h": AuditEvent.objects.filter(action="auth.login_failed", at__gte=day_ago).count(),
        "logins_24h": AuditEvent.objects.filter(action="auth.login", at__gte=day_ago).count(),
        "requests_24h": AccessLog.objects.filter(at__gte=day_ago).count(),
        "locked": locked,
        "sessions": active_sessions()[:50],
        "mfa_rows": mfa_rows,
        "expired": expired,
        "expiring": expiring,
        "max_age": max_age,
        "can_control": has_role(request.user, *CONTROL_ROLES),
        "page_title": "Security",
    }
    return render(request, "security/dashboard.html", ctx)


@require_POST
@role_required(*CONTROL_ROLES)
def acknowledge(request, pk):
    """Mark an alert as looked at, with a note."""
    alert = get_object_or_404(SecurityAlert, pk=pk, acknowledged_at__isnull=True)
    alert.acknowledged_at = timezone.now()
    alert.acknowledged_by = request.user
    alert.note = request.POST.get("note", "")[:300]
    alert.save(update_fields=["acknowledged_at", "acknowledged_by", "note"])
    audit.record("security.alert_acknowledged", alert, f"Alert '{alert.message[:80]}' acknowledged: {alert.note}")
    messages.success(request, "Alert acknowledged.")
    return redirect("security:dashboard")


@require_POST
@role_required("ict_admin")
def unlock(request):
    """Clear the lockout for a username (UM10011)."""
    from axes.utils import reset

    username = request.POST.get("username", "")[:150]
    reset(username=username)
    audit.record("security.unlocked", None, f"Lockout cleared for {username}")
    messages.success(request, f"Lockout cleared for {username}.")
    return redirect("security:dashboard")


def _parse_date(value, default):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def _activity(user, start, end):
    tz = timezone.get_current_timezone()
    lo = timezone.make_aware(datetime.combine(start, time.min), tz)
    hi = timezone.make_aware(datetime.combine(end, time.max), tz)
    events = AuditEvent.objects.filter(actor=user, at__range=(lo, hi))
    access = AccessLog.objects.filter(user=user, at__range=(lo, hi))
    return events, access


@role_required(*VIEW_ROLES)
def activity(request):
    """Everything one user did in a date range: business events and every page or download."""
    user_model = get_user_model()
    today = timezone.localdate()
    start = _parse_date(request.GET.get("from"), today - timedelta(days=6))
    end = _parse_date(request.GET.get("to"), today)
    target = user_model.objects.filter(pk=request.GET.get("user")).first() if request.GET.get("user") else None
    ctx = {"users": user_model.objects.order_by("username"), "target": target, "start": start, "end": end, "page_title": "User activity"}
    if target:
        events, access = _activity(target, start, end)
        timeline = sorted(
            [{"at": e.at, "kind": "event", "what": e.action, "detail": e.summary, "ip": e.ip_address} for e in events[:2000]]
            + [
                {
                    "at": a.at,
                    "kind": "page",
                    "what": f"{a.method} {a.path}",
                    "detail": f"{a.object_type} {a.object_ref}".strip(),
                    "ip": a.ip_address,
                    "status": a.status,
                }
                for a in access[:2000]
            ],
            key=lambda r: r["at"],
            reverse=True,
        )
        ctx.update(
            {
                "page": Paginator(timeline, 100).get_page(request.GET.get("page")),
                "events_count": events.count(),
                "pages_count": access.count(),
                "members_opened": access.filter(object_type="member").values("object_ref").distinct().count(),
                "sessions": target.tracked_sessions.all()[:20],
                "roles": sorted(role_names(target)),
                "can_control": has_role(request.user, *CONTROL_ROLES),
            }
        )
        audit.record("security.activity_viewed", target, f"Activity of {target.username} viewed for {start}–{end}")
    return render(request, "security/activity.html", ctx)


@role_required(*VIEW_ROLES)
def activity_csv(request):
    """CSV export of the same timeline."""
    target = get_object_or_404(get_user_model(), pk=request.GET.get("user"))
    today = timezone.localdate()
    start = _parse_date(request.GET.get("from"), today - timedelta(days=6))
    end = _parse_date(request.GET.get("to"), today)
    events, access = _activity(target, start, end)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="activity-{target.username}-{start}-{end}.csv"'
    writer = csv.writer(response)
    writer.writerow(["time", "type", "action_or_page", "record", "status", "ip_address"])
    rows = [(e.at, "event", e.action, e.summary, "", e.ip_address or "") for e in events.iterator()]
    rows += [(a.at, "page", f"{a.method} {a.path}", f"{a.object_type} {a.object_ref}".strip(), a.status, a.ip_address or "") for a in access.iterator()]
    for row in sorted(rows, key=lambda r: r[0]):
        writer.writerow([timezone.localtime(row[0]).strftime("%Y-%m-%d %H:%M:%S"), *row[1:]])
    audit.record("security.activity_exported", target, f"Activity of {target.username} exported for {start}–{end}")
    return response


@require_POST
@role_required(*CONTROL_ROLES)
def end_user_sessions(request, user_id):
    """Sign a user out everywhere."""
    target = get_object_or_404(get_user_model(), pk=user_id)
    count = end_sessions(target, by=request.user)
    from .services import raise_alert

    raise_alert("sessions_revoked", f"{request.user.username} ended {count} session(s) of {target.username}.", severity="low", user=target, dedupe_minutes=0)
    messages.success(request, f"{count} session(s) of {target.display_name()} ended.")
    return redirect(f"/security/activity/?user={target.pk}")
