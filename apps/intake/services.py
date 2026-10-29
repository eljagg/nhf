"""Online Intake module: doctor-portal submissions, online queue, work locks, assignment (OR10001–OR10010)."""

import hashlib
import hmac
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import users_with_role
from apps.core import audit
from apps.core.models import Centre
from apps.core.notifications import queue as queue_notification
from apps.interactions.services import log
from apps.members import services as member_services
from apps.members.models import Application, Member
from apps.rules.models import MedicalCondition


class SubmissionError(ValueError):
    """The portal payload cannot be accepted."""


def verify_signature(body: bytes, signature: str) -> bool:
    """HMAC-SHA256 of the raw body with the shared secret agreed with the portal."""
    secret = settings.PORTAL_SHARED_SECRET
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


def online_centre():
    """Online applications are worked by the head-office online unit."""
    return Centre.objects.filter(code="HO").first() or Centre.objects.first()


def receive_portal_submission(payload: dict) -> Application:
    """Turn a doctor-portal submission into an online application; validate the TRN at once (OR10002)."""
    patient = payload.get("patient") or {}
    doctor = payload.get("doctor") or {}
    kind = payload.get("kind", "new")
    if kind not in ("new", "change"):
        raise SubmissionError("kind must be 'new' or 'change'")
    reference = str(payload.get("reference", ""))[:60]
    if not reference:
        raise SubmissionError("reference is required")
    existing = Application.objects.filter(portal_reference=reference).first()
    if existing:
        return existing  # idempotent re-delivery
    trn = "".join(ch for ch in str(patient.get("trn", "")) if ch.isdigit())
    if len(trn) != 9:
        raise SubmissionError("patient.trn must be nine digits")
    try:
        dob = date.fromisoformat(patient.get("dob", "")) if patient.get("dob") else None
    except ValueError as exc:
        raise SubmissionError("patient.dob must be YYYY-MM-DD") from exc
    member = Member.objects.filter(trn=trn).first()
    if kind == "new" and member is not None:
        kind = "change"  # OR10006: a 'new' form for an existing member is processed as a change form
    if kind == "change" and member is None:
        kind = "new"
    with transaction.atomic():
        app = member_services.start_application(
            user=None,
            centre=online_centre(),
            channel="online",
            received_at=timezone.now(),
            kind=kind,
            trn=trn,
            form_first_name=str(patient.get("first_name", ""))[:60],
            form_last_name=str(patient.get("last_name", ""))[:60],
            form_dob=dob,
            member=member,
            portal_reference=reference,
        )
        app.phone_mobile = str(patient.get("mobile", ""))[:20] or app.phone_mobile
        app.email = str(patient.get("email", ""))[:200] or app.email
        app.doctor_mcj = str(doctor.get("mcj_number", ""))[:12]
        app.referring_doctor_name = str(doctor.get("name", ""))[:120]
        if kind == "change":
            app.change_conditions = True
        member_services.resolve_doctor(app, user=None)
        app.save()
        codes = payload.get("conditions") or []
        conds = list(MedicalCondition.objects.filter(code__in=codes, is_active=True))
        if conds and kind == "change":  # the doctor certifies additional conditions; existing ones stay
            for c in conds:
                app.conditions.get_or_create(condition=c, defaults={"severity": "moderate"})
        elif conds:
            member_services.set_conditions(app, [(c, "moderate") for c in conds])
        member_services.refresh_status(app)
        log(
            f"Online submission {reference} from {app.referring_doctor_name or 'doctor portal'} ({app.get_kind_display().lower()})",
            application=app,
            event="portal.received",
            kind="email",
        )
        audit.record("portal.received", app, f"Portal submission {reference} → {app.tracking_number}")
        if app.phone_mobile:
            queue_notification("application-received-online", "sms", app.phone_mobile, obj=app, tracking=app.tracking_number)
        for user in users_with_role("customer_care").exclude(email=""):
            queue_notification(
                "online-application-cc",
                "email",
                user.email,
                obj=app,
                recipient_user=user,
                link=f"/members/applications/{app.tracking_number}/",
                tracking=app.tracking_number,
                kind=app.get_kind_display(),
                trn_status="in progress",
            )
    return app


def take_work_lock(app, user):
    """OR10010: mark the record as being worked by this agent (heartbeat refreshed by the page)."""
    other = app.worked_by_other(user)
    if other:
        return other
    Application.objects.filter(pk=app.pk).update(worked_by=user, worked_heartbeat=timezone.now())
    return None


def release_work_lock(app, user):
    """Release when the agent leaves the record."""
    Application.objects.filter(pk=app.pk, worked_by=user).update(worked_by=None, worked_heartbeat=None)


def assign(app, *, to_user, by_user):
    """Supervisor assigns an application to an agent (TOR §4)."""
    app.assigned_to = to_user
    app.save(update_fields=["assigned_to", "updated_at"])
    log(f"Assigned to {to_user.display_name()} by {by_user.display_name()}", application=app, event="application.assigned", actor=by_user)
    audit.record("application.assigned", app, f"{app.tracking_number} assigned to {to_user.username}", actor=by_user)
