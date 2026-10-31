"""Escalation of overdue work (NT10003). Runs hourly; each person gets at most one digest per item type a day.

* Applications still open after `escalate-open-hours` → the supervisors of that centre (Head Office for online forms
  is just another centre), and managers when a centre has no supervisor.
* Doctors waiting for Medical Council confirmation after `escalate-doctor-days` → council confirmers and managers.
* SRN requests waiting after `escalate-srn-hours` → SRN approvers.
* Cards waiting to print after `escalate-print-hours` → print operators and supervisors of that centre.
"""

from collections import defaultdict
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import users_with_role
from apps.core.models import Notification, Parameter

DIGEST_HOURS = 20


def _recently_told(user, template):
    return Notification.objects.filter(recipient_user=user, template=template, created_at__gte=timezone.now() - timedelta(hours=DIGEST_HOURS)).exists()


def _tell(users, template, subject, body, link):
    told = 0
    for user in {u.pk: u for u in users}.values():
        if _recently_told(user, template):
            continue
        Notification.objects.create(
            channel="inapp", recipient_user=user, template=template, subject=subject, body=body, link=link, status="sent", sent_at=timezone.now()
        )
        told += 1
    return told


def _centre_staff(role, centre_id):
    return users_with_role(role).filter(centre_id=centre_id)


def run():
    from apps.cards.models import Card
    from apps.doctors.models import Doctor
    from apps.identity.models import SrnIssue
    from apps.members.models import Application

    now = timezone.now()
    out = {}

    hours = int(Parameter.get("escalate-open-hours"))
    late = Application.objects.filter(status__in=Application.OPEN_STATUSES, received_at__lt=now - timedelta(hours=hours)).select_related("centre")
    per_centre = defaultdict(list)
    for app in late:
        per_centre[app.centre_id].append(app)
    told = 0
    for centre_id, apps in per_centre.items():
        people = list(_centre_staff("supervisor", centre_id)) or list(users_with_role("manager"))
        refs = ", ".join(a.tracking_number for a in apps[:8]) + (f" and {len(apps) - 8} more" if len(apps) > 8 else "")
        told += _tell(
            people,
            "overdue-applications",
            f"{len(apps)} application(s) open more than {hours} hours at {apps[0].centre.name}",
            f"Still open after {hours} hours: {refs}. Assign or finish them today.",
            reverse("members:applications") + "?status=open",
        )
    out["applications"] = told

    days = int(Parameter.get("escalate-doctor-days"))
    waiting = Doctor.objects.filter(status="pending", created_at__lt=now - timedelta(days=days))
    n = waiting.count()
    out["doctors"] = (
        _tell(
            list(users_with_role("mcj_confirmer")) + list(users_with_role("manager")),
            "overdue-doctor-confirmations",
            f"{n} doctor(s) waiting for Medical Council confirmation more than {days} days",
            "Applications that name these doctors cannot be approved until they are confirmed or rejected.",
            reverse("doctors:confirmations"),
        )
        if n
        else 0
    )

    hours_srn = int(Parameter.get("escalate-srn-hours"))
    n = SrnIssue.objects.filter(status="requested", created_at__lt=now - timedelta(hours=hours_srn)).count()
    out["srn"] = (
        _tell(
            users_with_role("srn_approver"),
            "overdue-srn",
            f"{n} SRN request(s) waiting more than {hours_srn} hours",
            "The applicants cannot be registered until a Special Registration Number is approved or declined.",
            reverse("identity:srn-list"),
        )
        if n
        else 0
    )

    hours_print = int(Parameter.get("escalate-print-hours"))
    cards = Card.objects.filter(state="queued", queued_at__lt=now - timedelta(hours=hours_print)).values_list("centre_id", flat=True)
    per = defaultdict(int)
    for c in cards:
        per[c] += 1
    told = 0
    for centre_id, count in per.items():
        people = list(_centre_staff("print_operator", centre_id)) + list(_centre_staff("supervisor", centre_id))
        told += _tell(
            people,
            "overdue-cards",
            f"{count} card(s) waiting to print more than {hours_print} hours",
            "Members are waiting for these cards. Print them or record why they are held.",
            reverse("cards:queue"),
        )
    out["cards"] = told
    return out
