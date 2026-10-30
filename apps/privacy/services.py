"""Data-subject access exports and the retention sweep."""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import Notification, Parameter
from apps.interactions.services import log

from .models import RetentionRun


def member_export(member):
    """Everything the system holds about a member, as a JSON-ready dict (access request)."""

    def d(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    guardian = getattr(member, "guardian", None)
    return {
        "generated_at": timezone.now().isoformat(),
        "controller": "National Health Fund",
        "member": {
            "member_number": member.member_number,
            "trn_or_srn": member.trn,
            "is_srn": member.is_srn,
            "nis_number": member.nis_number,
            "name": member.full_name,
            "date_of_birth": d(member.dob),
            "gender": member.get_gender_display(),
            "mobile": member.phone_mobile,
            "home_phone": member.phone_home,
            "email": member.email,
            "address": ", ".join(p for p in [member.address_line1, member.address_line2, member.get_parish_display()] if p),
            "card_collection_centre": str(member.collection_centre or ""),
            "registered_at": d(member.registered_at),
            "consent_recorded_at": d(member.consent_at),
            "privacy_notice_version": member.consent_version,
            "status": member.get_status_display(),
        },
        "guardian": {"name": guardian.full_name, "relationship": guardian.relationship, "trn": guardian.trn, "phone": guardian.phone} if guardian else None,
        "medical_conditions": [
            {
                "condition": c.condition.name,
                "severity": c.get_severity_display(),
                "certified_by": str(c.certified_by or ""),
                "certified_on": d(c.certified_on),
                "active": c.active,
            }
            for c in member.conditions.select_related("condition", "certified_by")
        ],
        "programmes": [
            {"programme": e.programme.name, "since": d(e.enrolled_at), "ended": d(e.ended_at)} for e in member.enrolments.select_related("programme")
        ],
        "cards": [
            {
                "version": c.version_no,
                "reason": c.get_reason_display(),
                "state": c.get_state_display(),
                "queued": d(c.queued_at),
                "dispatched": d(c.dispatched_at),
            }
            for c in member.cards.all()
        ],
        "applications": [
            {
                "tracking_number": a.tracking_number,
                "kind": a.get_kind_display(),
                "channel": a.get_channel_display(),
                "received": d(a.received_at),
                "status": a.get_status_display(),
            }
            for a in member.applications.all()
        ],
        "interactions": [{"at": d(i.at), "type": i.get_kind_display(), "summary": i.summary} for i in member.interactions.all()[:500]],
        "recipients": "Tax Administration Jamaica (TRN validation, via the ICT Authority); Medical Council of Jamaica (doctor confirmation); "
        "claims adjudication (PHI); card production (ID Works).",
    }


def record_export(dsr, *, user):
    """Log the release of a copy of the data on the request and on the member."""
    dsr.export_count += 1
    if dsr.status == "open":
        dsr.status = "in_progress"
    dsr.handled_by = dsr.handled_by or user
    dsr.save(update_fields=["export_count", "status", "handled_by"])
    audit.record("privacy.dsr_export", dsr, f"Copy of data produced for {dsr.reference} ({dsr.member.member_number})", actor=user)
    log(f"Data-subject access request {dsr.reference}: copy of personal data produced", member=dsr.member, kind="note", event="privacy.dsr_export", actor=user)


def retention_candidates():
    """What the sweep would act on now."""
    from apps.members.models import Application
    from apps.security.models import AccessLog

    now = timezone.now()
    app_days = int(Parameter.get("retention-rejected-days"))
    log_days = int(Parameter.get("access-log-retention-days"))
    return {
        "rejected_applications": Application.objects.filter(
            status__in=("rejected", "terminated"), decided_at__lt=now - timedelta(days=app_days), anonymised_at__isnull=True
        ),
        "access_log": AccessLog.objects.filter(at__lt=now - timedelta(days=log_days)),
        "notifications": Notification.objects.filter(created_at__lt=now - timedelta(days=365)),
    }


ANONYMISE_FIELDS = {
    "form_first_name": "",
    "form_last_name": "",
    "form_dob": None,
    "first_name": "",
    "middle_name": "",
    "last_name": "",
    "dob": None,
    "phone_mobile": "",
    "phone_home": "",
    "email": "",
    "address_line1": "",
    "address_line2": "",
    "nis_number": "",
    "guardian_name": "",
    "guardian_trn": "",
    "guardian_phone": "",
    "referring_doctor_name": "",
}


def run_retention(*, dry_run=False, user=None):
    """Anonymise old rejected applications, purge old access-log rows and notifications. Approved records are never touched."""
    c = retention_candidates()
    results = {k: qs.count() for k, qs in c.items()}
    if not dry_run:
        with transaction.atomic():
            ids = list(c["rejected_applications"].values_list("pk", flat=True))
            if ids:
                from apps.members.models import Application

                Application.objects.filter(pk__in=ids).update(anonymised_at=timezone.now(), trn="", **ANONYMISE_FIELDS)
            c["access_log"].delete()
            c["notifications"].delete()
        audit.record("privacy.retention_run", None, f"Retention sweep: {results}", actor=user, **results)
    return RetentionRun.objects.create(dry_run=dry_run, results=results, run_by=user)
