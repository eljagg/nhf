"""Home, inbox, audit trail, integration log, health check."""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.roles import has_role, role_required
from apps.cards.models import Card
from apps.doctors.models import Doctor
from apps.identity.models import SrnIssue
from apps.members.models import Application, Member

from .models import AuditEvent, IntegrationRun, Notification


def healthz(request):
    """Liveness and database check for the load balancer and Railway."""
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})


@login_required
def home(request):
    """Counter home: today's work, queues and the quick start."""
    user = request.user
    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    open_apps = Application.objects.filter(status__in=Application.OPEN_STATUSES)
    from apps.accounts.scoping import scope_by_centre

    centre_apps = scope_by_centre(open_apps, user)
    stats = {
        "members": Member.objects.filter(status="active").count(),
        "today_received": Application.objects.filter(received_at__gte=start).count(),
        "today_approved": Application.objects.filter(decided_at__gte=start, status="approved").count(),
        "open": centre_apps.count(),
        "ready": centre_apps.filter(status="ready").count(),
        "online": open_apps.filter(channel="online").count(),
        "srn": SrnIssue.objects.filter(status="requested").count(),
        "mcj": Doctor.objects.filter(status="pending").count(),
        "print_queue": Card.objects.filter(state="queued").count(),
    }
    mine = open_apps.filter(Q(entered_by=user) | Q(assigned_to=user)).select_related("centre")[:10]
    by_channel = Application.objects.filter(received_at__gte=start - timedelta(days=6)).values("channel").annotate(n=Count("id")).order_by("-n")
    return render(request, "core/home.html", {"stats": stats, "mine": mine, "by_channel": by_channel, "page_title": "Home"})


@login_required
def notifications(request):
    """In-app inbox (NT10001, NT10004 links to records)."""
    qs = Notification.objects.filter(recipient_user=request.user, channel="inapp")
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    outbound = Notification.objects.exclude(channel="inapp").order_by("-created_at")[:15] if has_role(request.user, "manager", "supervisor") else []
    return render(request, "core/notifications.html", {"page": page, "outbound": outbound, "page_title": "Inbox"})


@require_POST
@login_required
def notification_open(request, pk):
    """Mark read and follow the link."""
    note = get_object_or_404(Notification, pk=pk, recipient_user=request.user)
    if not note.read_at:
        note.read_at = timezone.now()
        note.save(update_fields=["read_at"])
    return redirect(note.link or "core:notifications")


@role_required("auditor", "manager", "ict_admin")
def audit_trail(request):
    """Audit viewer (AL10001, DM10002)."""
    qs = AuditEvent.objects.select_related("actor")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(summary__icontains=q) | Q(action__icontains=q) | Q(object_id=q) | Q(actor__username__icontains=q))
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/audit.html", {"page": page, "q": q, "page_title": "Audit trail"})


@role_required("ict_admin", "manager", "auditor")
def integrations(request):
    """Integration Hub run log (IN10003)."""
    qs = IntegrationRun.objects.all()
    system = request.GET.get("system", "")
    if system:
        qs = qs.filter(system=system)
    summary = IntegrationRun.objects.values("system").annotate(n=Count("id"), failed=Count("id", filter=Q(ok=False))).order_by("system")
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/integrations.html", {"page": page, "summary": summary, "system": system, "page_title": "Integration Hub"})


@login_required
def image(request, pk):
    """Serve a stored image to a viewer whose role allows that kind."""
    from . import images
    from .models import StoredImage

    return images.serve(request, StoredImage.objects.filter(pk=pk).first())
