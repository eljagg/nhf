"""Data-subject access exports and the retention sweep."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core import audit
from apps.core.models import Notification, Parameter, StoredImage
from apps.interactions.services import log

from .models import ProcessingActivity, RetentionRun


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
            "processing_restricted_since": d(member.processing_restricted_at),
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
        "staff_id_records": get_user_model()
        .objects.filter(is_active=False, deactivated_at__lt=now - timedelta(days=int(Parameter.get("staff-id-retention-days"))))
        .filter(Q(id_document__isnull=False) | Q(photo__isnull=False) | ~Q(id_number="")),
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
            for user in c["staff_id_records"]:
                erase_staff_identity(user)
        audit.record("privacy.retention_run", None, f"Retention sweep: {results}", actor=user, **results)
    return RetentionRun.objects.create(dry_run=dry_run, results=results, run_by=user)


def erase_staff_identity(user):
    """Remove a former staff member's ID number, ID picture and photo (the account and its audit history stay)."""
    images = [i for i in (user.id_document_id, user.photo_id) if i]
    type(user).objects.filter(pk=user.pk).update(id_number="", id_type="", id_expiry=None, id_document=None, photo=None)
    StoredImage.objects.filter(pk__in=images).delete()
    audit.record("privacy.staff_identity_erased", user, f"ID number, ID picture and photo of former staff account {user.username} erased (retention)")


def restrict_processing(member, *, reason, user, dsr=None):
    """Objection / restriction: applications for this member cannot be approved until the restriction is lifted."""
    member.processing_restricted_at = timezone.now()
    member.processing_restriction_reason = reason[:300]
    member.save(update_fields=["processing_restricted_at", "processing_restriction_reason"])
    audit.record(
        "privacy.processing_restricted",
        member,
        f"Processing of member {member.member_number} restricted: {reason}",
        actor=user,
        dsr=dsr.reference if dsr else "",
    )


def lift_restriction(member, *, note, user, dsr=None):
    member.processing_restricted_at = None
    member.processing_restriction_reason = ""
    member.save(update_fields=["processing_restricted_at", "processing_restriction_reason"])
    audit.record(
        "privacy.restriction_lifted", member, f"Restriction on member {member.member_number} lifted: {note}", actor=user, dsr=dsr.reference if dsr else ""
    )


def dpo_contact():
    """Name, e-mail and phone of the DPO as configured, joined for notices."""
    parts = [Parameter.get("dpo-name"), Parameter.get("dpo-email"), Parameter.get("dpo-phone")]
    return ", ".join(p for p in parts if p) or "Data Protection Officer, National Health Fund (contact details not yet set in the back office)"


def breach_notice(breach, audience):
    """Draft notice text for the Information Commissioner or for the people affected (DPA 2020 breach notification)."""
    when = timezone.localtime(breach.discovered_at).strftime("%d %B %Y at %H:%M")
    occurred = timezone.localtime(breach.occurred_at).strftime("%d %B %Y at %H:%M") if breach.occurred_at else "not yet established"
    reg = Parameter.get("dpa-registration-number")
    if audience == "commissioner":
        lines = [
            "Notification of a personal data breach — Data Protection Act 2020",
            "",
            f"Data controller: National Health Fund{f' (registration {reg})' if reg else ''}",
            f"Reference: {breach.reference}",
            f"Became aware: {when}. Breach occurred: {occurred}.",
            "",
            "1. Facts of the breach",
            breach.description,
            "",
            "2. Nature and scale",
            f"Personal data concerned: {breach.data_categories}. Estimated number of people affected: {breach.subjects_affected}. Severity assessed as {breach.get_severity_display().lower()}.",
            "",
            "3. Likely consequences",
            breach.likely_consequences or "Under assessment.",
            "",
            "4. Measures taken or proposed",
            breach.actions or "Under way.",
            "",
            f"5. Data Protection Officer: {dpo_contact()}",
        ]
    else:
        lines = [
            "Important: about your personal information held by the National Health Fund",
            "",
            f"On {when} the National Health Fund became aware of an incident affecting personal information. Our reference is {breach.reference}.",
            "",
            f"What happened: {breach.description}",
            "",
            f"Information involved: {breach.data_categories}.",
            "",
            f"What we have done: {breach.actions or 'We are containing the incident and will write again with more information.'}",
            "",
            f"If you have questions, contact the Fund's Data Protection Officer: {dpo_contact()}. You may also contact the Office of the Information Commissioner.",
        ]
    return "\n".join(lines)


def draft_impact_assessment(year):
    """Starting text for this year's impact assessment, built from the processing register and the controls in place."""
    acts = ProcessingActivity.objects.all()
    scope = "Member Registration System and the personal data it processes:\n" + "\n".join(
        f"- {a.name}: {a.data_categories} ({'sensitive' if a.sensitive else 'not sensitive'}); recipients: {a.recipients or 'none outside the Fund'}; retention: {a.retention}"
        for a in acts
    )
    risks = "\n".join(
        [
            "- Unauthorised access to health information by staff without a need to know.",
            "- Account takeover through stolen passwords.",
            "- Loss or disclosure of identity data (TRN, NIS, ID documents) through a breach or lost device.",
            "- Inaccurate member data leading to wrong eligibility decisions.",
            "- Keeping data longer than necessary.",
            "- Over-sharing with third parties (claims adjudicator, card production, councils).",
            "- Unavailability of the service at the counters.",
        ]
    )
    measures = "\n".join(
        [
            "- Role-based access; medical conditions hidden from roles that do not process eligibility; page-by-page access log and bulk-viewing alerts.",
            "- Two-step sign-in for every staff account; Active Directory with hourly sync and in-session re-check; account suspension.",
            "- Field encryption for TRN payloads, notes, ID numbers and images; TLS; security headers; lockout and alerts.",
            "- Name and date of birth only from the TRN service; change forms; doctor and nurse confirmed with their council.",
            "- Daily retention sweep (rejected applications, access log, notifications, former staff ID records).",
            "- Processing register with recipients; data-sharing and processing agreements; consent recorded with notice version.",
            "- Breach register with 72-hour clock; data-subject requests with 30-day clock; restriction of processing on objection.",
        ]
    )
    return {"year": year, "scope": scope, "risks": risks, "measures": measures}
