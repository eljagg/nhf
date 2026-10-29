"""Members module business logic: intake, identity outcome, rules, approval, rejection, change forms.

Every state change is one transaction that also writes the interaction log and the audit trail
(design rule 4.2.1). Notifications and PHI calls are emitted after commit.
"""

from django.db import transaction
from django.utils import timezone

from apps.cards.models import Card, clean_card_name
from apps.core import audit
from apps.core.models import IntegrationRun
from apps.core.notifications import queue as queue_notification
from apps.doctors import services as doctor_services
from apps.identity import services as identity
from apps.interactions.services import log
from apps.rules import engine
from apps.rules.models import RejectionReason

from .models import Application, ApplicationCondition, Enrolment, Guardian, Member, MemberCondition, next_member_number


class ProcessingError(Exception):
    """A business rule stops the action; the message is shown to the agent."""


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------
def start_application(
    *, user, centre, channel, received_at, kind="new", trn="", form_first_name="", form_last_name="", form_dob=None, member=None, portal_reference=""
):
    """Create an application and start TRN validation (MR10001, MR10002, TV10001)."""
    trn = identity.clean_trn(trn)
    if kind == "new" and trn:
        existing = Member.objects.filter(trn=trn).first()
        if existing:
            raise ProcessingError(f"TRN {trn} already belongs to member {existing.member_number} ({existing.full_name}). Use a change form for this member.")
    if kind == "change" and member is None:
        member = Member.objects.filter(trn=trn).first()
        if member is None:
            raise ProcessingError("A change form must be for an existing member.")
    with transaction.atomic():
        app = Application.objects.create(
            kind=kind,
            channel=channel,
            centre=centre,
            received_at=received_at or timezone.now(),
            entered_by=user,
            member=member,
            trn=trn or (member.trn if member else ""),
            form_first_name=form_first_name,
            form_last_name=form_last_name,
            form_dob=form_dob,
            portal_reference=portal_reference,
            collection_centre=(member.collection_centre if member else centre),
        )
        if member is not None:
            _prefill_from_member(app, member)
        log(
            f"{app.get_kind_display()} {app.tracking_number} received ({app.get_channel_display()}) at {centre}",
            application=app,
            member=member,
            event="application.received",
            actor=user,
        )
        audit.record("application.created", app, f"{app.tracking_number} created ({app.get_kind_display()}, {app.get_channel_display()})", actor=user)
        if app.trn and not (member and member.is_srn):
            begin_identity_check(app, user=user)
        elif member is not None and member.is_srn:
            app.is_srn = True
            app.identity_confirmed = True
            app.save(update_fields=["is_srn", "identity_confirmed"])
    return app


def _prefill_from_member(app, member):
    """A change form starts from the member's current record."""
    for f in ("first_name", "middle_name", "last_name", "dob", "gender", "phone_mobile", "phone_home", "email", "address_line1", "address_line2", "parish"):
        setattr(app, f, getattr(member, f))
    app.collection_centre = member.collection_centre
    guardian = getattr(member, "guardian", None)
    if guardian:
        app.guardian_name, app.guardian_relationship, app.guardian_trn, app.guardian_phone = (
            guardian.full_name,
            guardian.relationship,
            guardian.trn,
            guardian.phone,
        )
    latest = member.conditions.filter(active=True).select_related("certified_by").first()
    if latest and latest.certified_by:
        app.doctor, app.doctor_mcj = latest.certified_by, latest.certified_by.mcj_number
    app.save()
    for mc in member.conditions.filter(active=True):
        ApplicationCondition.objects.get_or_create(application=app, condition=mc.condition, defaults={"severity": mc.severity})


def begin_identity_check(app, *, user):
    """Send the application's TRN to the TRN service. Each check is a fresh call (TV10008)."""
    form_identity = None
    if app.form_last_name or app.form_dob:
        form_identity = {"first_name": app.form_first_name, "last_name": app.form_last_name, "dob": app.form_dob.isoformat() if app.form_dob else ""}
    validation = identity.start_validation(app.trn, user=user, purpose="change" if app.kind == "change" else "application", form_identity=form_identity)
    app.trn_validation = validation
    if app.kind == "new":
        app.identity_confirmed = False
    app.save(update_fields=["trn_validation", "identity_confirmed", "updated_at"])
    return validation


def on_validation_complete(validation):
    """Apply a TRN result to the application(s) waiting on it."""
    for app in Application.objects.filter(trn_validation=validation, status__in=Application.OPEN_STATUSES):
        payload = validation.payload or {}
        if validation.status == "valid" and validation.match_result in ("match", "") and app.kind == "new":
            _copy_identity(app, payload)
            app.identity_confirmed = True
            app.save()
            log(f"TRN {app.trn} validated with the Tax Office; identity matches the form", application=app, event="trn.match")
        elif validation.status == "valid" and app.kind == "change":
            app.identity_confirmed = True
            app.save(update_fields=["identity_confirmed"])
            changed = [k for k in ("first_name", "middle_name", "last_name", "dob", "gender") if str(payload.get(k, "")) != str(getattr(app.member, k))]
            msg = f"TRN {app.trn} re-validated" + (f"; Tax Office record differs on {', '.join(changed)}" if changed else "; no identity change")
            log(msg, application=app, event="trn.refresh")
        elif validation.status == "valid":
            log(
                f"TRN {app.trn} validated but does not match the form ({', '.join(d['label'] for d in validation.differences)})",
                application=app,
                event="trn.mismatch",
            )
        elif validation.status == "invalid":
            log(f"TRN {app.trn} not found at the Tax Office", application=app, event="trn.invalid")
            if app.phone_mobile:
                queue_notification("trn-invalid", "sms", app.phone_mobile, obj=app, trn=app.trn, tracking=app.tracking_number)
        else:
            log(f"TRN service unavailable for {app.trn}: {validation.message}", application=app, event="trn.unavailable")
        refresh_status(app)


def _copy_identity(app, payload):
    app.first_name = payload.get("first_name", "")
    app.middle_name = payload.get("middle_name", "") or ""
    app.last_name = payload.get("last_name", "")
    app.dob = payload.get("dob") or None
    app.gender = payload.get("gender", "")
    if not app.address_line1:
        app.address_line1 = payload.get("address_line1", "")
        app.address_line2 = payload.get("address_line2", "")
        app.parish = payload.get("parish", "") or app.parish


def identity_changes(app):
    """Change forms: where the fresh Tax Office record differs from the member record (BR10003)."""
    validation = app.trn_validation
    if app.kind != "change" or not app.member or not validation or validation.status != "valid" or not validation.payload:
        return []
    labels = {"first_name": "First name", "middle_name": "Middle name", "last_name": "Last name", "dob": "Date of birth", "gender": "Gender"}
    out = []
    for key, label in labels.items():
        current = getattr(app.member, key)
        current = current.isoformat() if hasattr(current, "isoformat") else (current or "")
        fresh = validation.payload.get(key, "") or ""
        if str(current) != str(fresh):
            out.append({"label": label, "member": current, "taj": fresh})
    return out


def notify_invalid_trn(app, *, user):
    """TV10006 on demand: text the applicant that the TRN could not be validated."""
    if not app.phone_mobile:
        raise ProcessingError("Record the applicant's mobile number first.")
    note = queue_notification("trn-invalid", "sms", app.phone_mobile, obj=app, trn=app.trn, tracking=app.tracking_number)
    log(f"Applicant notified by SMS that TRN {app.trn} could not be validated", application=app, kind="sms", event="trn.invalid_notified", actor=user)
    return note


def accept_corrected_form(app, *, user):
    """The agent re-keyed the form details (typing error) — re-check against the Tax Office."""
    begin_identity_check(app, user=user)
    log("Form details corrected and TRN re-checked", application=app, event="trn.recheck", actor=user)


def terminate_for_mismatch(app, *, user, text=""):
    """TV10004/TV10005: end the application because the TRN identity does not match the form."""
    reason = RejectionReason.objects.get(code="trn_mismatch")
    return reject(app, user=user, reason=reason, text=text or "Identity on the form does not match the Tax Office record.", status="terminated")


def link_srn_request(app, issue):
    """Attach an SRN request to the application; it waits for management approval."""
    app.srn_issue = issue
    app.status = "awaiting"
    app.save(update_fields=["srn_issue", "status", "updated_at"])
    log(f"Special Registration Number requested for {issue.full_name}; awaiting management approval", application=app, event="srn.requested")


def on_srn_decided(issue):
    """Apply an approved SRN to the waiting application (SR10005)."""
    for app in Application.objects.filter(srn_issue=issue, status__in=Application.OPEN_STATUSES):
        if issue.status == "approved":
            app.trn, app.is_srn, app.identity_confirmed = issue.srn, True, True
            app.first_name, app.middle_name, app.last_name, app.dob, app.gender = issue.first_name, issue.middle_name, issue.last_name, issue.dob, issue.gender
            app.save()
            log(f"SRN {issue.srn} issued (approved by {issue.decided_by.display_name()})", application=app, event="srn.approved", actor=issue.decided_by)
        else:
            app.save()
            log(f"SRN request declined: {issue.decision_note}", application=app, event="srn.declined", actor=issue.decided_by)
        refresh_status(app)


# ---------------------------------------------------------------------------
# Rules and status
# ---------------------------------------------------------------------------
def evaluate(app):
    """Run the rules engine on an application (BR10004–BR10006)."""
    conditions = [ac.condition for ac in app.conditions.select_related("condition")]
    ctx = engine.RuleContext(
        dob=app.dob if not isinstance(app.dob, str) else timezone.datetime.fromisoformat(app.dob).date(),
        gender=app.gender,
        as_of=timezone.localtime(app.received_at).date(),
        has_guardian=bool(app.guardian_name and app.guardian_relationship),
        conditions=conditions,
        has_doctor=bool(app.doctor_mcj),
        identity_confirmed=app.identity_confirmed,
    )
    outcome = engine.evaluate(ctx)
    if app.doctor and app.doctor.status == "pending":
        outcome.findings.append(
            engine.Finding(
                "DV10003", "warning", f"MCJ {app.doctor.mcj_number} is awaiting confirmation with the Medical Council; approval waits for it.", "doctor_mcj"
            )
        )
    if app.doctor and app.doctor.status == "rejected":
        outcome.findings.append(
            engine.Finding(
                "DV10004",
                "error",
                f"MCJ {app.doctor.mcj_number} could not be confirmed by the Medical Council; the application must be rejected.",
                "doctor_mcj",
            )
        )
    if app.srn_issue and app.srn_issue.status == "requested":
        outcome.findings.append(engine.Finding("SR10001", "warning", "Waiting for management approval of the Special Registration Number."))
    if app.kind == "change" and app.reprint_reason and app.reprint_reason != "replacement" and not app.change_identity:
        outcome.findings.append(
            engine.Finding(
                "BR10008", "error", "A reprint for a name or date-of-birth change needs the identity refresh from the TRN service ticked.", "reprint_reason"
            )
        )
    return outcome


def refresh_status(app):
    """Set draft / awaiting / ready from the current findings."""
    if not app.is_open:
        return app
    outcome = evaluate(app)
    waiting = (app.doctor and app.doctor.status == "pending") or (app.srn_issue and app.srn_issue.status == "requested")
    app.status = "ready" if outcome.ok and not waiting else ("awaiting" if waiting else "draft")
    app.save(update_fields=["status", "updated_at"])
    return app


def set_conditions(app, condition_severities):
    """Replace the application's conditions with [(MedicalCondition, severity)]."""
    keep = set()
    for cond, severity in condition_severities:
        obj, _ = ApplicationCondition.objects.update_or_create(application=app, condition=cond, defaults={"severity": severity})
        keep.add(obj.pk)
    app.conditions.exclude(pk__in=keep).delete()


def resolve_doctor(app, *, user):
    """DV10001–DV10003 on save."""
    if not app.doctor_mcj:
        app.doctor = None
        return
    doctor = doctor_services.resolve(app.doctor_mcj, tracking=app.tracking_number, name_hint=app.referring_doctor_name, user=user)
    if doctor and app.doctor_id != doctor.pk and doctor.status == "pending":
        log(f"MCJ {doctor.mcj_number} is not in the NHF Doctors register; confirmation requested", application=app, event="doctor.unknown", actor=user)
    app.doctor = doctor
    app.doctor_mcj = doctor.mcj_number if doctor else ""


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------
def approve(app_id, *, user):
    """Process an application in one transaction (MR10003, MR10004, BR10005, BR10007).

    New: member number, member, conditions, guardian, enrolments, queued card. Change: apply the change form,
    reprint when the rules allow. Then the interaction, audit, and — after commit — PHI and the applicant SMS.
    """
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=app_id)
        if not app.is_open:
            raise ProcessingError(f"{app.tracking_number} is already {app.get_status_display().lower()}.")
        outcome = evaluate(app)
        if not outcome.ok:
            raise ProcessingError("Cannot approve: " + " ".join(f.message for f in outcome.errors))
        if app.doctor and app.doctor.status != "confirmed":
            raise ProcessingError("Cannot approve until the doctor is confirmed with the Medical Council.")
        if app.kind == "new":
            member = _create_member(app)
            card = _queue_card(member, app, reason="new", user=user)
            summary = f"Approved: member {member.member_number} issued; card queued at {card.centre}"
        else:
            member, card = _apply_change(app, user=user)
            summary = "Change form approved" + (f"; card v{card.version_no} queued ({card.get_reason_display().lower()})" if card else "")
        programmes = _sync_enrolments(member, outcome.programmes, user=user)
        app.member = member
        app.status = "approved"
        app.decided_at = timezone.now()
        app.decided_by = user
        app.worked_by = None
        app.save()
        if programmes:
            summary += f"; enrolled in {', '.join(p.name for p in programmes)}"
        log(summary, application=app, member=member, event="application.approved", actor=user)
        audit.record("application.approved", app, f"{app.tracking_number} approved → {member.member_number}", actor=user, card=card.pk if card else None)
        transaction.on_commit(lambda: _after_approval(app.pk, card.pk if card else None))
    return app


def _create_member(app):
    with identity.identity_write():
        member = Member.objects.create(
            member_number=next_member_number(),
            trn=app.trn,
            is_srn=app.is_srn,
            srn_annotation="Special Registration Number — no validated TRN" if app.is_srn else "",
            first_name=app.first_name,
            middle_name=app.middle_name,
            last_name=app.last_name,
            dob=app.dob,
            gender=app.gender,
            phone_mobile=app.phone_mobile,
            phone_home=app.phone_home,
            email=app.email,
            address_line1=app.address_line1,
            address_line2=app.address_line2,
            parish=app.parish,
            collection_centre=app.collection_centre or app.centre,
            registered_centre=app.centre,
            identity_refreshed_at=timezone.now() if not app.is_srn else None,
        )
    _write_guardian(member, app)
    _write_conditions(member, app)
    return member


def _write_guardian(member, app):
    if app.guardian_name:
        Guardian.objects.update_or_create(
            member=member,
            defaults={"full_name": app.guardian_name, "relationship": app.guardian_relationship, "trn": app.guardian_trn, "phone": app.guardian_phone},
        )


def _write_conditions(member, app):
    wanted = {ac.condition_id: ac.severity for ac in app.conditions.all()}
    for mc in member.conditions.filter(active=True):
        if mc.condition_id not in wanted:
            mc.active = False
            mc.save(update_fields=["active"])
    for cond_id, severity in wanted.items():
        MemberCondition.objects.update_or_create(
            member=member,
            condition_id=cond_id,
            active=True,
            defaults={"severity": severity, "certified_by": app.doctor, "certified_on": timezone.localtime(app.received_at).date()},
        )


def _apply_change(app, *, user):
    member = Member.objects.select_for_update().get(pk=app.member_id)
    changed = []
    if app.change_identity:
        payload = (app.trn_validation.payload if app.trn_validation and app.trn_validation.status == "valid" else None) or {}
        if not payload:
            raise ProcessingError("The identity refresh needs a successful TRN validation on this change form.")
        with identity.identity_write():
            for key in ("first_name", "middle_name", "last_name", "gender"):
                if str(payload.get(key, "") or "") != str(getattr(member, key)):
                    changed.append(key)
                    setattr(member, key, payload.get(key, "") or "")
            if payload.get("dob") and payload["dob"] != member.dob.isoformat():
                changed.append("dob")
                member.dob = payload["dob"]
            member.identity_refreshed_at = timezone.now()
            member.save()
        app.first_name, app.middle_name, app.last_name, app.dob, app.gender = member.first_name, member.middle_name, member.last_name, member.dob, member.gender
    if app.change_contact:
        for key in ("phone_mobile", "phone_home", "email", "address_line1", "address_line2", "parish"):
            if getattr(member, key) != getattr(app, key):
                changed.append(key)
                setattr(member, key, getattr(app, key))
        if app.collection_centre_id and member.collection_centre_id != app.collection_centre_id:
            member.collection_centre = app.collection_centre
            changed.append("collection_centre")
        member.save()
    if app.change_guardian:
        _write_guardian(member, app)
        changed.append("guardian")
    if app.change_conditions:
        _write_conditions(member, app)
        changed.append("conditions")
    card = None
    reason = app.reprint_reason
    if app.change_identity and {"first_name", "middle_name", "last_name"} & set(changed):
        reason = "name_change"
    elif app.change_identity and "dob" in changed:
        reason = "dob_change"
    if reason:  # BR10008: reprint only for replacement or a name/DOB change
        card = _queue_card(member, app, reason=reason, user=user)
    audit.record("member.changed", member, f"Change form {app.tracking_number} applied: {', '.join(changed) or 'no field changes'}", actor=user, fields=changed)
    return member, card


def _queue_card(member, app, *, reason, user):
    last = member.cards.order_by("-version_no", "-reprint_seq").first()
    version = 1 if last is None else last.version_no + 1  # BR10007
    card = Card(
        member=member,
        application=app,
        version_no=version,
        reason=reason,
        centre=member.collection_centre or app.centre,
        print_name=clean_card_name(member.full_name)[:60],
        queued_by=user,
    )
    card.encode_tracks()
    card.save()
    return card


def _sync_enrolments(member, programmes, *, user):
    added = []
    open_ids = set(member.enrolments.filter(ended_at__isnull=True).values_list("programme_id", flat=True))
    for prog in programmes:
        if prog.pk not in open_ids:
            Enrolment.objects.create(member=member, programme=prog, source="rule", enrolled_by=user)
            added.append(prog)
    return added


def _after_approval(app_id, card_id):
    """Post-commit: PHI upsert (mock adapter in Phase A) and the applicant SMS."""
    app = Application.objects.select_related("member", "collection_centre", "centre").get(pk=app_id)
    IntegrationRun.objects.create(
        system="phi",
        operation="upsert_beneficiary",
        adapter="mock",
        reference=app.member.member_number,
        message=f"beneficiary record passed; card {card_id or '—'} flagged for printing",
    )
    if card_id:
        Card.objects.filter(pk=card_id).update(phi_reconciled_at=timezone.now())
    if app.member.phone_mobile:
        queue_notification(
            "application-approved",
            "sms",
            app.member.phone_mobile,
            obj=app,
            tracking=app.tracking_number,
            member_number=app.member.member_number,
            centre=app.member.collection_centre or app.centre,
        )


def reject(app, *, user, reason, text="", status="rejected"):
    """MR10008/MR10009: reject with a reason; the reason is logged automatically."""
    with transaction.atomic():
        app = Application.objects.select_for_update().get(pk=app.pk)
        if not app.is_open:
            raise ProcessingError(f"{app.tracking_number} is already {app.get_status_display().lower()}.")
        app.status = status
        app.rejection_reason = reason
        app.rejection_text = text[:300]
        app.decided_at = timezone.now()
        app.decided_by = user
        app.worked_by = None
        app.save()
        verb = "Terminated" if status == "terminated" else "Rejected"
        log(f"{verb}: {reason.label}{' — ' + text if text else ''}", application=app, event=f"application.{status}", actor=user)
        audit.record(f"application.{status}", app, f"{app.tracking_number} {verb.lower()}: {reason.code}", actor=user, reason=reason.code)
        if app.phone_mobile:
            transaction.on_commit(
                lambda: queue_notification("application-rejected", "sms", app.phone_mobile, obj=app, tracking=app.tracking_number, reason=reason.label)
            )
    return app


def reject_for_unconfirmed_doctor(doctor, *, user):
    """DV10004: reject every open application certified by a doctor the MCJ could not confirm."""
    reason = RejectionReason.objects.get(code="doctor_unconfirmed")
    done = []
    for app in Application.objects.filter(doctor=doctor, status__in=Application.OPEN_STATUSES):
        done.append(reject(app, user=user, reason=reason, text=f"MCJ {doctor.mcj_number} not confirmed by the Medical Council."))
    return done


def update_contact(member, *, user, data):
    """MR10006: contact details changed directly on the profile, without an application."""
    changed = []
    for key in ("phone_mobile", "phone_home", "email", "address_line1", "address_line2", "parish"):
        if key in data and data[key] != getattr(member, key):
            changed.append(key)
            setattr(member, key, data[key])
    if changed:
        member.save()
        log(f"Contact details updated ({', '.join(changed)})", member=member, event="member.contact_updated", actor=user)
        audit.record("member.contact_updated", member, f"Contact details updated: {', '.join(changed)}", actor=user, fields=changed)
    return changed
