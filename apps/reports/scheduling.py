"""Scheduled report e-mails (NT10002 one-time and recurring notifications).

Each recipient gets the report as their own role would see it (a supervisor's copy is held to their centre, health
counts only reach clinical roles). Only reports of counts are scheduled, and tables that list individual people are
left out of e-mails, so an attachment never carries a person's details (Data Protection Act data minimisation).
Recipients who no longer hold a reporting role, are suspended or inactive are skipped automatically.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone

from apps.accounts.roles import has_role
from apps.core import audit
from apps.core.models import Notification

from . import datasets, export, standard
from .access import SCHEDULE_ROLES, can_see
from .filters import Period

log = logging.getLogger(__name__)


def _sections_for(report, user, period):
    if report.kind == "standard":
        key = report.standard_key
        if key not in standard.CATALOGUE or not can_see(user, standard.CATALOGUE[key][2]):
            return None
        built = standard.build(key, period, user)
        return built.title, [(t.title, t.headers, t.rows) for t in built.tables if not t.personal]
    defn = dict(report.definition)
    if not datasets.is_aggregate(defn):
        return None
    ds = datasets.get(defn.get("dataset"))
    if ds is None:
        return None
    # The schedule's period applies to the dataset's main date column.
    date_field = {"applications": "received_day", "members": "registered_day", "cards": "queued_day", "interactions": "day"}[ds.key]
    defn["filters"] = list(defn.get("filters") or []) + [
        {"field": date_field, "op": "gte", "value": period.start_date.isoformat()},
        {"field": date_field, "op": "lte", "value": period.end_date.isoformat()},
    ]
    headers, rows, _ = datasets.run(defn, user)
    return report.name, [("", headers, rows)]


def send_schedule(sched, *, manual=False):
    report = sched.report
    today = timezone.localdate()
    end = today - timedelta(days=1)
    period = Period(end - timedelta(days=sched.period_days - 1), end, label=f"{sched.period_days} days to {end:%d %b %Y}")
    sent, skipped = 0, 0
    for user in sched.recipients.filter(is_active=True):
        if user.is_suspended or not user.email or not has_role(user, *SCHEDULE_ROLES):
            skipped += 1
            continue
        try:
            built = _sections_for(report, user, period)
        except datasets.ReportError:
            built = None
        if built is None:
            skipped += 1
            continue
        title, sections = built
        meta = [
            f"Scheduled report for {user.get_full_name() or user.username}",
            f"Period: {period.start_date:%d %b %Y} – {period.end_date:%d %b %Y}",
            "Counts only; no personal details. Handle under the Data Protection Act 2020.",
        ]
        data = export.xlsx_bytes(sections, title=title, meta=meta)
        subject = f"NHF report: {report.name} ({period.start_date:%d %b} – {period.end_date:%d %b %Y})"
        body = (
            f"Hello {user.first_name or user.username},\n\n"
            f"Your scheduled report '{report.name}' is attached as an Excel file. It covers {period.start_date:%d %b %Y} to "
            f"{period.end_date:%d %b %Y} and shows only what your role may see.\n\n"
            "To change or stop this e-mail, open Reports in the Member Registration System.\n"
        )
        msg = EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])
        msg.attach(f"{export.csvsafe.filename(report.name)}-{end:%Y%m%d}.xlsx", data, export.XLSX)
        try:
            msg.send()
        except Exception:  # noqa: BLE001 - one recipient's mail failure must not stop the others
            log.exception("scheduled report e-mail failed for %s", user.username)
            skipped += 1
            continue
        Notification.objects.create(
            channel="email",
            to=user.email,
            recipient_user=user,
            template="scheduled-report",
            subject=subject,
            body=body,
            status="sent",
            sent_at=timezone.now(),
            object_type=report._meta.label_lower,
            object_id=str(report.pk),
        )
        sent += 1
    now = timezone.now()
    sched.last_run_at = now
    sched.last_result = f"Sent to {sent}" + (f", skipped {skipped}" if skipped else "")
    if not manual:
        sched.next_run_at = sched.compute_next_run(now)
    sched.save(update_fields=["last_run_at", "last_result", "next_run_at"])
    audit.record("report.schedule_sent", sched, f"'{report.name}' e-mailed to {sent} recipient(s)" + (" (sent now by hand)" if manual else ""), skipped=skipped)
    return f"'{report.name}' sent to {sent} recipient(s)" + (f"; {skipped} skipped (no reporting role, no e-mail, or suspended)" if skipped else "") + "."


def run_due():
    from .models import ReportSchedule

    now = timezone.now()
    results = []
    for sched in ReportSchedule.objects.filter(active=True, next_run_at__lte=now).select_related("report"):
        results.append(send_schedule(sched))
    return results
