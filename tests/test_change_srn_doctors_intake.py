"""Change forms and reprints, SRN workflow, doctor confirmation, online intake API."""

import hashlib
import hmac
import json
from datetime import date

import pytest
from django.utils import timezone

from apps.doctors import services as doctor_services
from apps.doctors.models import Doctor
from apps.identity import services as identity
from apps.identity.models import TajIdentity
from apps.members import services
from apps.members.models import Application, Member
from apps.rules.models import MedicalCondition

from .test_counter_journey import complete, start

pytestmark = pytest.mark.django_db


def registered(agent, doctor, run_commits, trn, first, last, dob, *codes):
    app = complete(start(agent, run_commits, trn, first, last, dob), agent, doctor, *codes)
    with run_commits():
        return services.approve(app.pk, user=agent).member


def test_change_form_name_change_from_trn_service_reprints_with_new_version(agent, taj, doctor, run_commits):
    # Registered as Thompson; the Tax Office record now says Thompson-Clarke.
    TajIdentity.objects.filter(trn="100200306").update(last_name="Thompson")
    member = registered(agent, doctor, run_commits, "100200306", "Kerry-Ann", "Thompson", date(1985, 1, 23), "asthma")
    TajIdentity.objects.filter(trn="100200306").update(last_name="Thompson-Clarke")
    with run_commits():
        change = services.start_application(user=agent, centre=agent.centre, channel="walk_in", received_at=timezone.now(), kind="change", member=member)
    change.refresh_from_db()
    change.declaration_signed = True
    change.change_identity = True
    change.save()
    services.refresh_status(change)
    with run_commits():
        services.approve(change.pk, user=agent)
    member.refresh_from_db()
    assert member.last_name == "Thompson-Clarke"
    cards = list(member.cards.order_by("version_no"))
    assert [c.version_no for c in cards] == [1, 2] and cards[1].reason == "name_change"


def test_contact_only_change_form_does_not_reprint(agent, taj, doctor, run_commits):
    member = registered(agent, doctor, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), "hypertension")
    with run_commits():
        change = services.start_application(user=agent, centre=agent.centre, channel="walk_in", received_at=timezone.now(), kind="change", member=member)
    change.refresh_from_db()
    change.declaration_signed = True
    change.change_contact, change.address_line1 = True, "1 New Street"
    change.save()
    services.refresh_status(change)
    services.approve(change.pk, user=agent)
    member.refresh_from_db()
    assert member.address_line1 == "1 New Street" and member.cards.count() == 1


def test_reprint_for_name_change_without_identity_refresh_is_blocked(agent, taj, doctor, run_commits):
    member = registered(agent, doctor, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), "hypertension")
    with run_commits():
        change = services.start_application(user=agent, centre=agent.centre, channel="walk_in", received_at=timezone.now(), kind="change", member=member)
    change.refresh_from_db()
    change.declaration_signed = True
    change.reprint_reason = "name_change"
    change.save()
    assert "BR10008" in [f.rule for f in services.evaluate(change).errors]
    change.reprint_reason = "replacement"
    change.save()
    services.refresh_status(change)
    services.approve(change.pk, user=agent)
    assert list(member.cards.values_list("version_no", "reason").order_by("version_no")) == [(1, "new"), (2, "replacement")]


def test_contact_quick_edit_without_application(agent, taj, doctor, run_commits):
    member = registered(agent, doctor, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), "hypertension")
    changed = services.update_contact(member, user=agent, data={"phone_mobile": "876-555-1212", "email": "m@example.com"})
    assert set(changed) == {"phone_mobile", "email"}
    assert member.interactions.filter(event="member.contact_updated").exists()


def test_srn_request_approval_and_registration(agent, manager, taj, doctor, run_commits):
    with run_commits():
        app = services.start_application(
            user=agent,
            centre=agent.centre,
            channel="walk_in",
            received_at=timezone.now(),
            form_first_name="Jane",
            form_last_name="Doe",
            form_dob=date(1990, 2, 2),
        )
        issue = identity.request_srn(
            user=agent, first_name="Jane", middle_name="", last_name="Doe", dob=date(1990, 2, 2), gender="F", reason="No TRN issued yet"
        )
        services.link_srn_request(app, issue)
    assert issue.duplicate_check["clear"]
    with pytest.raises(PermissionError):
        identity.approve_srn(issue, user=agent)
    identity.approve_srn(issue, user=manager)
    issue.refresh_from_db()
    assert issue.srn.startswith("9") and len(issue.srn) == 9
    app.refresh_from_db()
    assert app.is_srn and app.trn == issue.srn and app.identity_confirmed and app.last_name == "Doe"
    app = complete(app, agent, doctor, "asthma")
    member = services.approve(app.pk, user=agent).member
    assert member.is_srn and member.trn == issue.srn and "Special Registration" in member.srn_annotation


def test_srn_duplicate_check_flags_trn_register_match(agent, taj):
    issue = identity.request_srn(
        user=agent, first_name="Marcia", middle_name="", last_name="Campbell", dob=date(1979, 3, 14), gender="F", reason="Lost TRN card"
    )
    assert not issue.duplicate_check["clear"] and issue.duplicate_check["trn_register"] == ["100200301"]


def test_srn_generator_never_collides():
    numbers = {identity.generate_srn() for _ in range(200)}
    assert len(numbers) == 200 and all(n.startswith("9") and len(n) == 9 for n in numbers)


def test_unknown_doctor_confirmation_then_rejection(agent, manager, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor_mcj = "99901"
    services.resolve_doctor(app, user=agent)
    app.save()
    services.set_conditions(app, [(MedicalCondition.objects.get(code="hypertension"), "mild")])
    services.refresh_status(app)
    assert app.status == "awaiting" and Doctor.objects.get(mcj_number="99901").status == "pending"
    rejected = doctor_services.reject(app.doctor, user=manager, note="MCJ has no such registration")
    app.refresh_from_db()
    assert rejected and app.status == "rejected" and app.rejection_reason.code == "doctor_unconfirmed"


def test_unknown_doctor_confirmed_makes_application_ready(agent, manager, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor_mcj = "99902"
    app.consent_given = True
    app.declaration_signed = app.doctor_signed = True
    app.address_line1, app.parish, app.phone_mobile = "12 Hope Road", "AND", "876-555-0100"
    services.resolve_doctor(app, user=agent)
    app.save()
    services.set_conditions(app, [(MedicalCondition.objects.get(code="hypertension"), "mild")])
    services.refresh_status(app)
    doctor_services.confirm(app.doctor, user=manager, note="Confirmed by phone")
    app.refresh_from_db()
    assert services.refresh_status(app).status == "ready"


def _signed(client, payload, secret="test-portal-secret", ts=None, nonce=None):
    import time
    import uuid

    body = json.dumps(payload).encode()
    ts = str(int(time.time())) if ts is None else ts
    nonce = nonce or uuid.uuid4().hex
    sig = "sha256=" + hmac.new(secret.encode(), f"{ts}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/intake/portal/", data=body, content_type="application/json", HTTP_X_PORTAL_SIGNATURE=sig, HTTP_X_PORTAL_TIMESTAMP=ts, HTTP_X_PORTAL_NONCE=nonce
    )


def test_portal_intake_requires_signature_and_creates_online_application(client, agent, taj, doctor, django_capture_on_commit_callbacks):
    payload = {
        "reference": "DP-1",
        "kind": "new",
        "patient": {"trn": "100200301", "first_name": "Marcia", "last_name": "Campbell", "dob": "1979-03-14", "mobile": "876-555-0101"},
        "doctor": {"mcj_number": "10001", "name": "Dr Kevin Spence"},
        "conditions": ["hypertension"],
        "consent": True,
    }
    assert client.post("/api/intake/portal/", data=payload, content_type="application/json").status_code == 401
    assert _signed(client, payload, secret="wrong").status_code == 401
    with django_capture_on_commit_callbacks(execute=True):
        response = _signed(client, payload)
    assert response.status_code == 201, response.content
    app = Application.objects.get(portal_reference="DP-1")
    assert app.channel == "online" and app.kind == "new" and app.identity_confirmed and app.status == "ready"
    assert app.interactions.filter(event="portal.received").exists()
    assert _signed(client, payload).json()["tracking_number"] == app.tracking_number  # idempotent re-delivery
    assert _signed(client, payload, nonce="fixed-nonce-0123456789").status_code == 201
    assert _signed(client, payload, nonce="fixed-nonce-0123456789").json()["detail"] == "nonce already used"  # replay refused
    assert _signed(client, payload, ts="1000000000").status_code == 401  # stale timestamp
    assert _signed(client, ["not", "an", "object"]).status_code == 400


def test_portal_new_form_for_existing_member_becomes_change(client, agent, taj, doctor, run_commits):
    member = registered(agent, doctor, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), "hypertension")
    payload = {
        "reference": "DP-2",
        "kind": "new",
        "patient": {"trn": member.trn, "first_name": "Marcia", "last_name": "Campbell", "dob": "1979-03-14"},
        "doctor": {"mcj_number": "10001"},
        "conditions": ["diabetes"],
    }
    with run_commits():
        assert _signed(client, payload).status_code == 201
    app = Application.objects.get(portal_reference="DP-2")
    assert app.kind == "change" and app.member == member
    assert set(app.conditions.values_list("condition__code", flat=True)) == {"hypertension", "diabetes"}


def test_member_numbers_are_unique_and_sequential(agent, taj, doctor, run_commits):
    a = registered(agent, doctor, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), "hypertension")
    b = registered(agent, doctor, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20), "diabetes")
    assert int(b.member_number) == int(a.member_number) + 1
    assert Member.objects.count() == 2
