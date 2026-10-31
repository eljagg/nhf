"""Dashboard figures (RA10002 dashboards, RA10003 near-real-time): computed live on each refresh."""

import statistics
from datetime import timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.cards.models import Card
from apps.core.models import Parameter
from apps.members.models import Application, Enrolment, Member

from . import charts
from .standard import _apps, _fmt_minutes, _pct

AGE_BUCKETS = [("Under 1 hour", 0, 1), ("1–4 hours", 1, 4), ("4–24 hours", 4, 24), ("1–3 days", 24, 72), ("Over 3 days", 72, None)]


def dashboard(period):
    now = timezone.now()
    tz = timezone.get_current_timezone()
    target = int(Parameter.get("same-day-minutes"))
    received = _apps(period)
    decided = _apps(period, by="decided_at")
    n_received = received.count()
    n_approved = decided.filter(status="approved").count()
    n_rejected = decided.filter(status__in=("rejected", "terminated")).count()

    open_now = Application.objects.filter(status__in=Application.OPEN_STATUSES)
    if period.centre:
        open_now = open_now.filter(centre=period.centre)
    if period.channel:
        open_now = open_now.filter(channel=period.channel)
    ages = [(now - r).total_seconds() / 3600 for r in open_now.values_list("received_at", flat=True)]
    buckets = [(label, sum(1 for a in ages if a >= lo and (hi is None or a < hi))) for label, lo, hi in AGE_BUCKETS]

    walk = [(d - r).total_seconds() / 60 for r, d in decided.filter(channel="walk_in", status="approved").values_list("received_at", "decided_at")]
    walk_median = statistics.median(walk) if walk else None
    within = sum(1 for m in walk if m <= target)

    cards = Card.objects.filter(state="queued")
    members = Member.objects.filter(status="active")
    if period.centre:
        cards = cards.filter(centre=period.centre)
        members = members.filter(registered_centre=period.centre)
    n_online = received.filter(channel="online").count()

    days = period.days
    rec = dict(received.annotate(d=TruncDate("received_at", tzinfo=tz)).values("d").annotate(n=Count("id")).values_list("d", "n"))
    app = dict(decided.filter(status="approved").annotate(d=TruncDate("decided_at", tzinfo=tz)).values("d").annotate(n=Count("id")).values_list("d", "n"))
    labels_t, keys, keyfn = charts.buckets(days)
    labels = dict(Application.CHANNELS)
    by_channel = list(received.values("channel").annotate(n=Count("id")).order_by("-n"))
    reasons = list(decided.filter(status__in=("rejected", "terminated")).values("rejection_reason__label").annotate(n=Count("id")).order_by("-n")[:6])
    programmes = list(
        Enrolment.objects.filter(member__in=members, ended_at__isnull=True).values("programme__name").annotate(n=Count("member", distinct=True)).order_by("-n")
    )

    kpis = [
        {"label": "Applications received", "value": f"{n_received:,}", "note": f"{n_online:,} online ({_pct(n_online, n_received)})"},
        {"label": "Approved", "value": f"{n_approved:,}", "note": f"Approval rate {_pct(n_approved, n_approved + n_rejected)}"},
        {
            "label": "Open now",
            "value": f"{len(ages):,}",
            "note": f"{open_now.filter(status='ready').count():,} ready to approve",
            "warn": any(a >= 24 for a in ages),
        },
        {
            "label": "Walk-in median, receipt to approval",
            "value": _fmt_minutes(walk_median),
            "note": f"{_pct(within, len(walk))} within {target} min" if walk else f"Target {target} min",
            "warn": walk_median is not None and walk_median > target,
        },
        {
            "label": "Cards waiting to print",
            "value": f"{cards.count():,}",
            "note": f"{Card.objects.filter(state='queued', queued_at__lt=now - timedelta(days=1)).count():,} waiting over a day",
        },
        {
            "label": "Active members",
            "value": f"{members.count():,}",
            "note": f"{members.filter(registered_at__gte=period.start, registered_at__lt=period.end).count():,} new in the period",
        },
    ]
    return {
        "kpis": kpis,
        "daily": charts.lines(labels_t, [("Received", charts.series_by(days, rec, keyfn, keys)), ("Approved", charts.series_by(days, app, keyfn, keys))]),
        "daily_unit": "week" if len(days) > 92 and len(days) <= 400 else ("month" if len(days) > 400 else "day"),
        "channels": charts.bars([(labels.get(r["channel"], r["channel"]), r["n"]) for r in by_channel]),
        "ageing": charts.bars(buckets, highlight="Over 3 days", empty="Nothing open."),
        "reasons": charts.bars([(r["rejection_reason__label"] or "No reason recorded", r["n"]) for r in reasons], empty="No rejections in the period."),
        "programmes": charts.bars([(r["programme__name"], r["n"]) for r in programmes]),
        "refreshed": timezone.localtime(now),
        "open_over_day": sum(1 for a in ages if a >= 24),
    }
