"""Standard reports (RP10001 in-platform reports, RP10002 membership and operational metrics, RA10001 member behaviour).

Each report takes the shared period/centre/channel filters and returns one or more tables (and a chart where it
helps). Tables marked `personal` list individual people or staff and are never put in scheduled e-mails.
"""

import statistics
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.cards.models import Card
from apps.core.models import Parameter
from apps.doctors.models import Doctor
from apps.identity.models import SrnIssue
from apps.interactions.models import Interaction
from apps.members.models import Application, Enrolment, Member, MemberCondition

from . import charts
from .access import can_see
from .datasets import _age_band


@dataclass
class Table:
    title: str
    headers: list
    rows: list
    note: str = ""
    chart: str = ""
    personal: bool = False


@dataclass
class Report:
    key: str
    title: str
    description: str
    sensitivity: str = "open"
    tables: list = field(default_factory=list)


def _apps(period, *, by="received_at"):
    qs = Application.objects.filter(**{f"{by}__gte": period.start, f"{by}__lt": period.end})
    if period.centre:
        qs = qs.filter(centre=period.centre)
    if period.channel:
        qs = qs.filter(channel=period.channel)
    return qs


def _pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "—"


def _minutes(td):
    return round(td.total_seconds() / 60, 1) if td is not None else None


def _percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo), 1)


def _fmt_minutes(m):
    if m is None:
        return "—"
    if m < 120:
        return f"{m:.0f} min"
    if m < 60 * 48:
        return f"{m / 60:.1f} h"
    return f"{m / 1440:.1f} days"


# --- reports -----------------------------------------------------------------------------------
def applications_summary(period, user):
    qs = _apps(period)
    rows = []
    per_centre = (
        qs.values("centre__name")
        .annotate(
            received=Count("id"),
            approved=Count("id", filter=Q(status="approved")),
            rejected=Count("id", filter=Q(status__in=("rejected", "terminated"))),
            open=Count("id", filter=Q(status__in=Application.OPEN_STATUSES)),
            new=Count("id", filter=Q(kind="new")),
            change=Count("id", filter=Q(kind="change")),
        )
        .order_by("-received")
    )
    tot = dict.fromkeys(("received", "approved", "rejected", "open", "new", "change"), 0)
    for r in per_centre:
        rows.append(
            [
                r["centre__name"],
                r["received"],
                r["new"],
                r["change"],
                r["approved"],
                r["rejected"],
                r["open"],
                _pct(r["approved"], r["approved"] + r["rejected"]),
            ]
        )
        for k in tot:
            tot[k] += r[k]
    if rows:
        rows.append(
            [
                "Total",
                tot["received"],
                tot["new"],
                tot["change"],
                tot["approved"],
                tot["rejected"],
                tot["open"],
                _pct(tot["approved"], tot["approved"] + tot["rejected"]),
            ]
        )
    by_channel = list(qs.values("channel").annotate(n=Count("id")).order_by("-n"))
    labels = dict(Application.CHANNELS)
    return [
        Table(
            "Applications by centre",
            ["Centre", "Received", "New", "Change forms", "Approved", "Rejected", "Still open", "Approval rate"],
            rows,
            "Approval rate = approved ÷ (approved + rejected) for applications received in the period.",
        ),
        Table(
            "Applications by channel",
            ["Channel", "Received", "Share"],
            [[labels.get(r["channel"], r["channel"]), r["n"], _pct(r["n"], tot["received"])] for r in by_channel],
            chart=charts.bars([(labels.get(r["channel"], r["channel"]), r["n"]) for r in by_channel]),
        ),
    ]


def turnaround(period, user):
    target = int(Parameter.get("same-day-minutes"))
    decided = _apps(period, by="decided_at").filter(status__in=("approved", "rejected")).values_list("channel", "received_at", "decided_at", "kind")
    by_channel = {}
    for channel, received, decided_at, _kind in decided:
        by_channel.setdefault(channel, []).append((decided_at - received).total_seconds() / 60)
    labels = dict(Application.CHANNELS)
    rows = []
    for channel, mins in sorted(by_channel.items(), key=lambda kv: -len(kv[1])):
        within = sum(1 for m in mins if m <= target)
        rows.append(
            [labels.get(channel, channel), len(mins), _fmt_minutes(statistics.median(mins)), _fmt_minutes(_percentile(mins, 0.9)), _pct(within, len(mins))]
        )
    walk = sorted(by_channel.get("walk_in", []))
    daily = {}
    for channel, received, decided_at, _kind in decided:
        if channel == "walk_in":
            daily.setdefault(timezone.localtime(decided_at).date(), []).append((decided_at - received).total_seconds() / 60)
    days = period.days
    series = [round(statistics.median(daily[d]), 1) if d in daily else 0 for d in days]
    return [
        Table(
            "Time from receipt to decision",
            ["Channel", "Decided", "Median", "90% decided within", f"Within {target} min"],
            rows,
            f"Same-day target at the counter: {target} minutes (parameter same-day-minutes). Online and mailed forms are expected to take longer.",
        ),
        Table(
            "Walk-in median by day",
            ["Day", "Median minutes"],
            [[d.isoformat(), v] for d, v in zip(days, series, strict=True) if v],
            chart=_median_chart(days, daily, target) if walk else "",
        ),
    ]


def _median_chart(days, daily, target):
    """Walk-in median turnaround per day, week or month, against the same-day target."""
    labels, keys, keyfn = charts.buckets(days)
    grouped = {}
    for d, mins in daily.items():
        grouped.setdefault(keyfn(d), []).extend(mins)
    values = [round(statistics.median(grouped[k]), 1) if k in grouped else 0 for k in keys]
    return charts.lines(labels, [("Walk-in median (minutes)", values)], target=target, target_label=f"{target}-minute target")


def rejections(period, user):
    qs = _apps(period, by="decided_at").filter(status__in=("rejected", "terminated"))
    total = qs.count()
    rows = list(qs.values("rejection_reason__label").annotate(n=Count("id")).order_by("-n"))
    return [
        Table(
            "Rejections by reason",
            ["Reason", "Rejected", "Share"],
            [[r["rejection_reason__label"] or "No reason recorded", r["n"], _pct(r["n"], total)] for r in rows],
            chart=charts.bars([(r["rejection_reason__label"] or "No reason recorded", r["n"]) for r in rows]),
        )
    ]


def membership(period, user):
    members = Member.objects.filter(status="active")
    if period.centre:
        members = members.filter(registered_centre=period.centre)
    total = members.count()
    new = members.filter(registered_at__gte=period.start, registered_at__lt=period.end).count()
    prog = list(
        Enrolment.objects.filter(member__in=members, ended_at__isnull=True).values("programme__name").annotate(n=Count("member", distinct=True)).order_by("-n")
    )
    from apps.core.models import PARISHES

    parishes = dict(PARISHES)
    by_parish = list(members.values("parish").annotate(n=Count("id")).order_by("-n"))
    bands = list(members.annotate(band=_age_band()).values("band", "gender").annotate(n=Count("id")).order_by("band"))
    band_rows = {}
    for r in bands:
        band_rows.setdefault(r["band"], {"M": 0, "F": 0})[r["gender"] or "M"] = r["n"]
    order = ["0–18", "19–39", "40–59", "60+", "Unknown"]
    plwd = members.filter(plwd=True).count()
    return [
        Table(
            "Membership at a glance",
            ["Measure", "Value"],
            [
                ["Active members", total],
                ["New members in the period", new],
                ["Persons living with a disability (JCPD double subsidy)", plwd],
                ["Members aged 60+ (JADEP age)", sum(v["M"] + v["F"] for k, v in band_rows.items() if k == "60+")],
                ["Children under 19 (double subsidy)", sum(v["M"] + v["F"] for k, v in band_rows.items() if k == "0–18")],
            ],
            "Counts are of active members now; the period applies to new registrations only.",
        ),
        Table(
            "Members by programme",
            ["Programme", "Members", "Share of active"],
            [[r["programme__name"], r["n"], _pct(r["n"], total)] for r in prog],
            chart=charts.bars([(r["programme__name"], r["n"]) for r in prog]),
        ),
        Table(
            "Members by age and gender",
            ["Age band", "Female", "Male", "Total"],
            [[b, band_rows[b]["F"], band_rows[b]["M"], band_rows[b]["F"] + band_rows[b]["M"]] for b in order if b in band_rows],
        ),
        Table(
            "Members by parish",
            ["Parish", "Members", "Share"],
            [[parishes.get(r["parish"], r["parish"] or "Not recorded"), r["n"], _pct(r["n"], total)] for r in by_parish],
            chart=charts.bars([(parishes.get(r["parish"], r["parish"] or "Not recorded"), r["n"]) for r in by_parish]),
        ),
    ]


def conditions(period, user):
    qs = MemberCondition.objects.filter(active=True, member__status="active")
    if period.centre:
        qs = qs.filter(member__registered_centre=period.centre)
    rows = list(
        qs.values("condition__name")
        .annotate(
            n=Count("member", distinct=True),
            severe=Count("member", distinct=True, filter=Q(severity="severe")),
            new=Count("member", distinct=True, filter=Q(added_at__gte=period.start, added_at__lt=period.end)),
        )
        .order_by("-n")
    )
    return [
        Table(
            "Members by certified condition",
            ["Condition", "Members", "Of which severe", "Added in the period"],
            [[r["condition__name"], r["n"], r["severe"], r["new"]] for r in rows],
            "A member with two conditions is counted once under each.",
            chart=charts.bars([(r["condition__name"], r["n"]) for r in rows[:15]]),
        )
    ]


def cards(period, user):
    qs = Card.objects.all()
    if period.centre:
        qs = qs.filter(centre=period.centre)
    span = {"queued_at__gte": period.start, "queued_at__lt": period.end}
    rows = []
    for c in (
        qs.filter(**span)
        .values("centre__name")
        .annotate(
            queued=Count("id"),
            printed=Count("id", filter=Q(printed_at__isnull=False)),
            verified=Count("id", filter=Q(verified_at__isnull=False)),
            dispatched=Count("id", filter=Q(dispatched_at__isnull=False)),
            spoiled=Count("id", filter=Q(state="spoiled")),
        )
        .order_by("-queued")
    ):
        rows.append([c["centre__name"], c["queued"], c["printed"], c["verified"], c["dispatched"], c["spoiled"]])
    waiting = list(qs.filter(state="queued").values("centre__name").annotate(n=Count("id")).order_by("-n"))
    waits = [(p - q).total_seconds() / 3600 for q, p in qs.filter(**span, printed_at__isnull=False).values_list("queued_at", "printed_at") if p and q]
    reasons = list(qs.filter(**span).values("reason").annotate(n=Count("id")).order_by("-n"))
    return [
        Table(
            "Card production by centre",
            ["Centre", "Queued", "Printed", "Verified", "Dispatched", "Spoiled"],
            rows,
            f"Median time from queue to print: {statistics.median(waits):.1f} h." if waits else "No cards printed in the period.",
        ),
        Table("Waiting to print now", ["Centre", "Cards"], [[r["centre__name"], r["n"]] for r in waiting]),
        Table("Why cards were produced", ["Reason", "Cards"], [[dict(Card.REASONS).get(r["reason"], r["reason"]), r["n"]] for r in reasons]),
    ]


def online_intake(period, user):
    qs = _apps(period).filter(channel="online")
    total = qs.count()
    decided = list(qs.filter(decided_at__isnull=False).values_list("received_at", "decided_at"))
    mins = [(d - r).total_seconds() / 60 for r, d in decided]
    top = list(qs.values("doctor_mcj", "doctor__last_name", "doctor__first_name").annotate(n=Count("id")).order_by("-n")[:20])
    return [
        Table(
            "Online applications from doctors",
            ["Measure", "Value"],
            [
                ["Received", total],
                ["Approved", qs.filter(status="approved").count()],
                ["Rejected", qs.filter(status__in=("rejected", "terminated")).count()],
                ["Still open", qs.filter(status__in=Application.OPEN_STATUSES).count()],
                ["Change forms (existing members)", qs.filter(kind="change").count()],
                ["Median time to decision", _fmt_minutes(statistics.median(mins)) if mins else "—"],
            ],
        ),
        Table(
            "Doctors sending the most applications",
            ["MCJ no.", "Doctor", "Applications"],
            [[r["doctor_mcj"], f"Dr {r['doctor__first_name'] or ''} {r['doctor__last_name'] or ''}".strip(), r["n"]] for r in top],
            personal=True,
        ),
    ]


def doctors(period, user):
    status = dict(Doctor.STATUSES)
    by_status = list(Doctor.objects.values("status").annotate(n=Count("id")).order_by("-n"))
    pending = Doctor.objects.filter(status="pending")
    now = timezone.now()
    ages = [(now - d.created_at).days for d in pending.only("created_at")]
    return [
        Table("NHF Doctors register", ["Status", "Doctors"], [[status.get(r["status"], r["status"]), r["n"]] for r in by_status]),
        Table(
            "Confirmations with the Medical Council",
            ["Measure", "Value"],
            [
                ["Added to the register in the period", Doctor.objects.filter(created_at__gte=period.start, created_at__lt=period.end).count()],
                ["Waiting for confirmation now", len(ages)],
                ["Oldest waiting (days)", max(ages) if ages else 0],
                ["Confirmed in the period", Doctor.objects.filter(confirmed_with_mcj_at__gte=period.start, confirmed_with_mcj_at__lt=period.end).count()],
            ],
        ),
    ]


def srn(period, user):
    qs = SrnIssue.objects.filter(created_at__gte=period.start, created_at__lt=period.end)
    decided = [(s.decided_at - s.created_at).total_seconds() / 3600 for s in qs.filter(decided_at__isnull=False).only("created_at", "decided_at")]
    return [
        Table(
            "Special Registration Numbers",
            ["Measure", "Value"],
            [
                ["Requested in the period", qs.count()],
                ["Approved", qs.filter(status="approved").count()],
                ["Declined", qs.filter(status="declined").count()],
                ["Waiting for a manager", SrnIssue.objects.filter(status="requested").count()],
                ["Median hours to decision", f"{statistics.median(decided):.1f}" if decided else "—"],
            ],
        )
    ]


def staff_productivity(period, user):
    qs = _apps(period)
    entered = {r["entered_by__username"]: r["n"] for r in qs.values("entered_by__username").annotate(n=Count("id"))}
    decided = _apps(period, by="decided_at")
    dec = {
        r["decided_by__username"]: r
        for r in decided.values("decided_by__username").annotate(
            approved=Count("id", filter=Q(status="approved")), rejected=Count("id", filter=Q(status__in=("rejected", "terminated")))
        )
    }
    walk = {}
    for who, r, d in decided.filter(channel="walk_in", status="approved").values_list("decided_by__username", "received_at", "decided_at"):
        walk.setdefault(who, []).append((d - r).total_seconds() / 60)
    people = sorted({k for k in list(entered) + list(dec) if k}, key=lambda k: -(entered.get(k, 0) + dec.get(k, {}).get("approved", 0)))
    rows = [
        [
            p,
            entered.get(p, 0),
            dec.get(p, {}).get("approved", 0),
            dec.get(p, {}).get("rejected", 0),
            _fmt_minutes(statistics.median(walk[p])) if p in walk else "—",
        ]
        for p in people
    ]
    return [
        Table(
            "Work by staff member",
            ["Staff", "Entered", "Approved", "Rejected", "Walk-in median"],
            rows,
            "Entered = applications keyed in the period; approved/rejected = decisions made in the period.",
            personal=True,
        )
    ]


def member_activity(period, user):
    changes = _apps(period).filter(kind="change")
    total = changes.count()
    kinds = [
        ("Change member details", changes.filter(change_contact=True).count()),
        ("Update medical record", changes.filter(change_conditions=True).count()),
        ("Change guardian", changes.filter(change_guardian=True).count()),
        ("Name / date of birth from TRN", changes.filter(change_identity=True).count()),
        ("Replace card", changes.exclude(reprint_reason="").count()),
    ]
    inter = Interaction.objects.filter(at__gte=period.start, at__lt=period.end, member__isnull=False)
    if period.centre:
        inter = inter.filter(centre=period.centre)
    by_kind = list(inter.values("kind").annotate(n=Count("id"), members=Count("member", distinct=True)).order_by("-n"))
    kind_labels = dict(Interaction.KINDS)
    year_ago = timezone.now() - timedelta(days=365)
    repeat = list(
        Card.objects.filter(queued_at__gte=year_ago, reason="replacement")
        .values("member__member_number")
        .annotate(n=Count("id"))
        .filter(n__gte=2)
        .order_by("-n")[:50]
    )
    channel_mix = list(changes.values("channel").annotate(n=Count("id")).order_by("-n"))
    labels = dict(Application.CHANNELS)
    return [
        Table(
            "What existing members asked for",
            ["Request", "Change forms", "Share"],
            [[k, n, _pct(n, total)] for k, n in kinds],
            "One change form can ask for more than one thing.",
            chart=charts.bars(kinds),
        ),
        Table("How existing members reached NHF", ["Channel", "Change forms"], [[labels.get(r["channel"], r["channel"]), r["n"]] for r in channel_mix]),
        Table(
            "Contact with members (interaction log)",
            ["Kind", "Interactions", "Members"],
            [[kind_labels.get(r["kind"], r["kind"]), r["n"], r["members"]] for r in by_kind],
        ),
        Table(
            "Members with two or more replacement cards in 12 months",
            ["Member no.", "Replacement cards"],
            [[r["member__member_number"], r["n"]] for r in repeat],
            "Worth a look: frequent replacements can point to a lost-card pattern or misuse.",
            personal=True,
        ),
    ]


def daily_activity(period, user):
    days = period.days
    tz = timezone.get_current_timezone()
    rec = dict(_apps(period).annotate(d=TruncDate("received_at", tzinfo=tz)).values("d").annotate(n=Count("id")).values_list("d", "n"))
    app = dict(
        _apps(period, by="decided_at")
        .filter(status="approved")
        .annotate(d=TruncDate("decided_at", tzinfo=tz))
        .values("d")
        .annotate(n=Count("id"))
        .values_list("d", "n")
    )
    cq = Card.objects.filter(printed_at__gte=period.start, printed_at__lt=period.end)
    if period.centre:
        cq = cq.filter(centre=period.centre)
    printed = dict(cq.annotate(d=TruncDate("printed_at", tzinfo=tz)).values("d").annotate(n=Count("id")).values_list("d", "n"))
    rows = [[d.isoformat(), rec.get(d, 0), app.get(d, 0), printed.get(d, 0)] for d in days]
    labels, keys, keyfn = charts.buckets(days)
    return [
        Table(
            "Day by day",
            ["Day", "Received", "Approved", "Cards printed"],
            rows,
            chart=charts.lines(
                labels,
                [
                    ("Received", charts.series_by(days, rec, keyfn, keys)),
                    ("Approved", charts.series_by(days, app, keyfn, keys)),
                    ("Cards printed", charts.series_by(days, printed, keyfn, keys)),
                ],
            ),
        )
    ]


CATALOGUE = {
    "daily-activity": ("Day-by-day activity", "Applications received and approved, and cards printed, each day.", "open", daily_activity),
    "applications": (
        "Applications by centre and channel",
        "Received, approved, rejected and still open, by centre and by channel.",
        "open",
        applications_summary,
    ),
    "turnaround": ("Turnaround and the 15-minute target", "How long applications take from receipt to decision, by channel.", "open", turnaround),
    "rejections": ("Rejections by reason", "Why applications were not approved.", "open", rejections),
    "membership": ("Membership", "Active members by programme, age band, gender and parish.", "open", membership),
    "conditions": ("Members by medical condition", "How many members have each certified condition (clinical roles only).", "health", conditions),
    "cards": ("Card production", "Cards queued, printed, verified, dispatched and spoiled, by centre.", "open", cards),
    "online": ("Online applications from doctors", "Volumes and decision time for the doctor portal.", "open", online_intake),
    "doctors": ("Doctor validation", "The NHF Doctors register and Medical Council confirmations.", "open", doctors),
    "srn": ("Special Registration Numbers", "SRNs requested, approved and declined.", "open", srn),
    "staff": ("Staff productivity", "Applications entered and decided by each staff member.", "open", staff_productivity),
    "member-activity": ("Member behaviour", "What existing members ask for, how they reach NHF, and repeat card replacements.", "open", member_activity),
}


def available(user):
    return [(k, v[0], v[1]) for k, v in CATALOGUE.items() if can_see(user, v[2])]


def build(key, period, user):
    title, description, sensitivity, fn = CATALOGUE[key]
    if not can_see(user, sensitivity):
        raise PermissionError(key)
    tables = fn(period, user)
    if not can_see(user, "personal"):
        tables = [t for t in tables if not t.personal]
    return Report(key, title, description, sensitivity, tables)


__all__ = ["CATALOGUE", "Report", "Table", "available", "build"]
