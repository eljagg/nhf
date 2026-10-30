"""Counter journey: TRN validation, match, rules, approval, rejection (the three demonstration use cases)."""

from datetime import date

import pytest
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.cards.models import Card
from apps.core.models import AuditEvent, IntegrationRun, Notification, Parameter
from apps.identity.services import identity_write
from apps.interactions.models import Interaction
from apps.members import services
from apps.members.models import Application, Member
from apps.rules.models import MedicalCondition, RejectionReason

pytestmark = pytest.mark.django_db


def start(agent, run_commits, trn, first, last, dob, **kw):
    with run_commits():
        app = services.start_application(
            user=agent,
            centre=agent.centre,
            channel=kw.pop("channel", "walk_in"),
            received_at=timezone.now(),
            trn=trn,
            form_first_name=first,
            form_last_name=last,
            form_dob=dob,
            **kw,
        )
    app.refresh_from_db()
    return app


def complete(app, agent, doctor, *codes, guardian=False):
    app.doctor_mcj = doctor.mcj_number
    app.phone_mobile = "876-555-0100"
    app.consent_given = True
    if guardian:
        app.guardian_name, app.guardian_relationship = "Janet Brown", "Mother"
    services.resolve_doctor(app, user=agent)
    app.save()
    services.set_conditions(app, [(MedicalCondition.objects.get(code=c), "moderate") for c in codes])
    return services.refresh_status(app)


def test_trn_match_fills_locked_fields_from_the_tax_office(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "MARCIA", "campbell", date(1979, 3, 14))
    assert app.identity_confirmed
    assert (app.first_name, app.middle_name, app.last_name, app.gender) == ("Marcia", "Angela", "Campbell", "F")
    assert app.trn_validation.status == "valid" and app.trn_validation.match_result == "match"
    assert app.tracking_number.startswith(f"NHF-A-{timezone.localdate().year}-")
    assert IntegrationRun.objects.filter(system="trn", ok=True).exists()


def test_trn_payload_is_encrypted_at_rest(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT payload FROM identity_trnvalidation WHERE id = %s", [app.trn_validation_id])
        raw = cur.fetchone()[0]
    assert "Campbell" not in raw and raw.startswith("gAAAA")


def test_mismatch_shows_differences_and_terminate_rejects(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marsha", "Campbell", date(1979, 3, 14))
    assert not app.identity_confirmed
    assert app.trn_validation.match_result == "mismatch"
    assert [d["field"] for d in app.trn_validation.differences] == ["first_name"]
    services.terminate_for_mismatch(app, user=agent)
    app.refresh_from_db()
    assert app.status == "terminated" and app.rejection_reason.code == "trn_mismatch"
    assert app.interactions.filter(event="application.terminated").exists()


def test_corrected_form_rechecks_and_matches(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marsha", "Campbell", date(1979, 3, 14))
    app.form_first_name = "Marcia"
    app.save()
    with run_commits():
        services.accept_corrected_form(app, user=agent)
    app.refresh_from_db()
    assert app.identity_confirmed and app.first_name == "Marcia"


def test_invalid_trn_sms_to_applicant(agent, taj, run_commits):
    app = start(agent, run_commits, "100999999", "No", "Body", date(1980, 1, 1))
    assert app.trn_validation.status == "invalid"
    app.phone_mobile = "876-555-0199"
    app.save()
    with run_commits():
        services.notify_invalid_trn(app, user=agent)
    sms = Notification.objects.get(template="trn-invalid")
    assert sms.channel == "sms" and "ending 999" in sms.body and "100999999" not in sms.body and sms.status == "previewed"


def test_service_outage_keeps_application_open_and_opens_breaker(agent, taj, run_commits):
    cache.clear()
    Parameter.objects.update_or_create(key="mock-trn-service-down", defaults={"value": True})
    for _ in range(3):
        app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    assert app.trn_validation.status == "unavailable" and app.is_open
    Parameter.objects.filter(key="mock-trn-service-down").update(value=False)
    app = start(agent, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20))
    assert app.trn_validation.status == "unavailable" and "circuit open" in IntegrationRun.objects.first().message
    cache.clear()


def test_guardian_required_under_18(agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200302", "Tyrese", "Brown", date(2014, 7, 2))
    app = complete(app, agent, doctor, "asthma")
    assert app.status == "draft"
    assert "BR10004" in [f.rule for f in services.evaluate(app).errors]
    app = complete(app, agent, doctor, "asthma", guardian=True)
    assert app.status == "ready"


def test_bph_blocked_for_female_applicant(agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200305", "Paulette", "Reid", date(1972, 9, 1))
    app = complete(app, agent, doctor, "bph")
    assert [f.rule for f in services.evaluate(app).errors] == ["BR10006"]
    with pytest.raises(services.ProcessingError):
        services.approve(app.pk, user=agent)


def test_approval_issues_member_card_enrolments_jadep_log_and_phi(agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20))
    app = complete(app, agent, doctor, "diabetes", "glaucoma")
    assert app.status == "ready"
    with run_commits():
        app = services.approve(app.pk, user=agent)
    member = app.member
    assert member.member_number.isdigit() and len(member.member_number) == 10
    assert set(member.enrolments.values_list("programme__code", flat=True)) == {"nhf", "jadep"}
    card = Card.objects.get(member=member)
    assert card.state == "queued" and card.version_no == 1 and card.track2.startswith(f";{member.member_number}=")
    assert card.phi_reconciled_at is not None
    assert IntegrationRun.objects.filter(system="phi", reference=member.member_number).exists()
    assert member.interactions.filter(event="application.approved").exists()
    assert AuditEvent.objects.filter(action="application.approved", object_id=str(app.pk)).exists()
    assert Notification.objects.filter(template="application-approved", channel="sms").exists()
    assert member.conditions.filter(active=True).count() == 2


def test_new_application_for_existing_member_is_refused(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    services.approve(app.pk, user=agent)
    with pytest.raises(services.ProcessingError, match="change form"):
        services.start_application(user=agent, centre=agent.centre, channel="walk_in", received_at=timezone.now(), trn="100200301")


def test_reject_needs_reason_and_is_logged(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    reason = RejectionReason.objects.get(code="incomplete_form")
    services.reject(app, user=agent, reason=reason, text="Page 2 missing")
    app.refresh_from_db()
    assert app.status == "rejected" and app.rejection_text == "Page 2 missing"
    assert "Form incomplete" in app.interactions.get(event="application.rejected").summary
    with pytest.raises(services.ProcessingError):
        services.reject(app, user=agent, reason=reason)


def test_protected_identity_fields_locked_in_the_database(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    member = services.approve(app.pk, user=agent).member
    member.last_name = "Typed-By-Hand"
    with pytest.raises(DatabaseError, match="TRN Validator"), transaction.atomic():
        member.save()
    with pytest.raises(DatabaseError), transaction.atomic():
        Member.objects.filter(pk=member.pk).update(dob=date(2000, 1, 1))
    with identity_write():
        Member.objects.filter(pk=member.pk).update(last_name="Campbell-Lee")
    member.refresh_from_db()
    assert member.last_name == "Campbell-Lee"
    member.phone_mobile = "876-555-7777"
    member.save()  # contact fields are not protected


def test_interactions_and_audit_are_append_only_in_the_database(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    with pytest.raises(DatabaseError), transaction.atomic():
        Interaction.objects.filter(application=app).update(summary="rewritten")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.all().delete()


def test_open_applications_listed(agent, taj, run_commits):
    start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    assert Application.objects.filter(status__in=Application.OPEN_STATUSES).count() == 1
