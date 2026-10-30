"""v0.2: NIS number, consent, user tracking, security hardening, Data Protection Act module."""

import json
from datetime import date, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.core.models import AuditEvent, Parameter
from apps.members import services
from apps.members.identifiers import is_valid_nis
from apps.members.models import Application
from apps.privacy.models import Breach, DataSubjectRequest
from apps.privacy.services import run_retention
from apps.rules.models import RejectionReason
from apps.security.models import AccessLog, SecurityAlert, UserSession

from .conftest import PASSWORD, make_user
from .test_counter_journey import complete, start

pytestmark = pytest.mark.django_db


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def approved_member(agent, doctor, run_commits, nis=""):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.nis_number = nis
    app.save()
    services.refresh_status(app)
    with run_commits():
        return services.approve(app.pk, user=agent).member


# --- NIS ---------------------------------------------------------------------
def test_nis_format_is_configurable():
    assert is_valid_nis("B204517") and is_valid_nis("b 204-517") and is_valid_nis("G721675") and is_valid_nis("")
    assert not is_valid_nis("123456789")  # one letter + six digits only (NHF decision, 30 Oct 2026)
    assert not is_valid_nis("BB12345")
    Parameter.objects.update_or_create(key="nis-format-regex", defaults={"value": r"^[A-Z]{2}[0-9]{5}$"})
    assert is_valid_nis("BB12345") and not is_valid_nis("B204517")


def test_nis_copied_to_member_and_searchable(client, agent, taj, doctor, run_commits):
    member = approved_member(agent, doctor, run_commits, nis="B204517")
    assert member.nis_number == "B204517"
    login(client, agent)
    response = client.get("/members/search/?q=b204517")
    assert member.member_number in response.content.decode()


def test_duplicate_or_malformed_nis_blocks_approval(agent, taj, doctor, run_commits):
    approved_member(agent, doctor, run_commits, nis="B204517")
    app = complete(start(agent, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20)), agent, doctor, "diabetes")
    app.nis_number = "B204517"
    app.save()
    assert any(f.rule == "NIS" and "already belongs" in f.message for f in services.evaluate(app).errors)
    app.nis_number = "XYZ"
    app.save()
    assert any(f.rule == "NIS" and "format" in f.message for f in services.evaluate(app).errors)


def test_contact_form_edits_nis_and_rejects_duplicates(client, agent, taj, doctor, run_commits):
    member = approved_member(agent, doctor, run_commits)
    login(client, agent)
    client.post(
        f"/members/{member.member_number}/",
        {"action": "contact", "c-nis_number": "c 123-456", "c-phone_mobile": member.phone_mobile, "c-parish": member.parish},
    )
    member.refresh_from_db()
    assert member.nis_number == "C123456"


# --- Consent -----------------------------------------------------------------
def test_consent_required_before_approval(client, agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.consent_given = False
    app.save()
    assert "JDPA" in [f.rule for f in services.evaluate(app).errors]
    login(client, agent)
    client.post(
        f"/members/applications/{app.tracking_number}/",
        {
            "consent_given": "on",
            "declaration_signed": "on",
            "doctor_signed": "on",
            "address_line1": "12 Hope Road",
            "parish": "AND",
            "phone_mobile": "876-555-0100",
            "doctor_mcj": doctor.mcj_number,
            "collection_centre": agent.centre_id,
            f"cond_{app.conditions.first().condition_id}": "on",
        },
    )
    app.refresh_from_db()
    assert app.consent_given and app.consent_at and app.consent_version == Parameter.get("privacy-notice-version") and app.status == "ready"
    member = services.approve(app.pk, user=agent).member
    assert member.consent_at is not None


# --- User tracking -----------------------------------------------------------
def test_access_log_and_activity_screen(client, agent, auditor, taj, doctor, run_commits):
    member = approved_member(agent, doctor, run_commits)
    login(client, agent)
    client.get(f"/members/{member.member_number}/")
    row = AccessLog.objects.filter(user=agent, object_type="member").first()
    assert row and row.object_ref == member.member_number and row.status == 200
    assert UserSession.objects.filter(user=agent, ended_at__isnull=True).exists()
    client.logout()
    login(client, auditor)
    page = client.get(f"/security/activity/?user={agent.pk}").content.decode()
    assert member.member_number in page
    csv_body = client.get(f"/security/activity/export.csv?user={agent.pk}").content.decode()
    assert csv_body.startswith("time,type,action_or_page") and member.member_number in csv_body
    assert AuditEvent.objects.filter(action="security.activity_exported").exists()


def test_sign_out_everywhere_ends_the_session(client, agent, ict, settings):
    settings.MFA_REQUIRED_ROLES = []
    login(client, agent)
    assert client.get("/").status_code == 200
    from django.test import Client

    admin = Client()
    login(admin, ict)
    admin.post(f"/security/users/{agent.pk}/end-sessions/")
    assert UserSession.objects.filter(user=agent, ended_at__isnull=False).exists()
    response = client.get("/")
    assert response.status_code == 302 and "/accounts/login/" in response.url


# --- Security alerts ----------------------------------------------------------
def test_failed_sign_in_alert(client, agent):
    for _ in range(5):
        client.post("/accounts/login/", {"username": agent.username, "password": "wrong-password"})
    alert = SecurityAlert.objects.get(kind="failed_logins")
    assert agent.username in alert.message and alert.user == agent


def test_bulk_viewing_alert(client, agent, taj, doctor, run_commits):
    from apps.security.services import check_bulk_viewing

    Parameter.objects.update_or_create(key="alert-bulk-view-per-hour", defaults={"value": 10})  # 10 is the floor
    a = approved_member(agent, doctor, run_commits)
    login(client, agent)
    client.get(f"/members/{a.member_number}/")
    assert AccessLog.objects.filter(user=agent, object_type="member", object_ref=a.member_number).exists()  # page views are logged
    for n in range(11):
        AccessLog.objects.create(user=agent, method="GET", path=f"/members/{n}/", status=200, object_type="member", object_ref=f"20000001{n:02d}")
    check_bulk_viewing(agent)
    assert SecurityAlert.objects.filter(kind="bulk_viewing", user=agent).exists()


def test_trn_failure_alert(agent, taj, run_commits):
    Parameter.objects.update_or_create(key="alert-failed-trn-per-hour", defaults={"value": 3})  # 3 is the floor
    for _ in range(4):
        start(agent, run_commits, "100999999", "No", "Body", date(1980, 1, 1))
    assert SecurityAlert.objects.filter(kind="trn_failures", user=agent).exists()


# --- Passwords ----------------------------------------------------------------
def test_password_history_blocks_reuse(agent):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    agent.set_password("First-Password-2026!")
    agent.save()
    agent.set_password("Second-Password-2026!")
    agent.save()
    with pytest.raises(ValidationError):
        validate_password("First-Password-2026!", agent)
    validate_password("Brand-New-Password-77!", agent)


def test_expired_password_forces_change(client, agent):
    login(client, agent)
    type(agent).objects.filter(pk=agent.pk).update(password_changed_at=timezone.now() - timedelta(days=91))
    response = client.get("/")
    assert response.status_code == 302 and response.url == "/accounts/password/"
    response = client.post("/accounts/password/", {"old_password": PASSWORD, "new_password1": "Fresh-Password-2026!", "new_password2": "Fresh-Password-2026!"})
    assert response.status_code == 302
    assert client.get("/").status_code == 200


def test_password_reset_email_and_throttle(client, agent):
    for _ in range(7):
        client.post("/accounts/password/reset/", {"email": agent.email})
    assert len(mail.outbox) == 5
    assert "/accounts/password/reset/" in mail.outbox[0].body


def test_unverified_manager_cannot_reach_account_pages(client, manager):
    login(client, manager)
    response = client.get("/accounts/temporary-roles/")
    assert response.status_code == 302 and response.url == "/accounts/mfa/setup/"


def test_security_dashboard_renders(client, auditor):
    login(client, auditor)
    assert b"Two-step sign-in coverage" in client.get("/security/").content


# --- Data Protection Act ---------------------------------------------------------
@pytest.fixture
def dpo(centre, settings):
    settings.MFA_REQUIRED_ROLES = []
    return make_user("dpo.officer", "dpo", centre=centre)


def test_access_request_export(client, dpo, agent, taj, doctor, run_commits):
    member = approved_member(agent, doctor, run_commits, nis="B204517")
    login(client, dpo)
    response = client.post("/privacy/requests/", {"requester_name": member.full_name, "kind": "access", "channel": "counter", "member_lookup": member.trn})
    dsr = DataSubjectRequest.objects.get()
    assert response.status_code == 302 and dsr.member == member
    assert (dsr.due_at - dsr.received_at).days == 30
    assert client.get(f"/privacy/requests/{dsr.pk}/export.json").status_code == 302  # identity not yet checked
    dsr.identity_checked = True
    dsr.save()
    body = json.loads(client.get(f"/privacy/requests/{dsr.pk}/export.json").content)
    assert body["member"]["member_number"] == member.member_number and body["member"]["nis_number"] == "B204517"
    assert body["medical_conditions"][0]["condition"] == "Hypertension"
    assert member.interactions.filter(event="privacy.dsr_export").exists()


def test_breach_clock(client, dpo):
    login(client, dpo)
    client.post(
        "/privacy/breaches/",
        {
            "title": "Lost laptop",
            "discovered_at": (timezone.localtime() - timedelta(hours=80)).strftime("%Y-%m-%dT%H:%M"),
            "severity": "high",
            "status": "open",
            "description": "Laptop left in a taxi",
            "data_categories": "names",
            "subjects_affected": 10,
        },
    )
    breach = Breach.objects.get()
    assert breach.report_overdue and breach.hours_left < 0
    assert breach.reference.startswith(f"BR-{timezone.localdate().year}-")


def test_retention_anonymises_old_rejections_only(agent, taj, doctor, run_commits):
    approved = approved_member(agent, doctor, run_commits)
    app = start(agent, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20))
    services.reject(app, user=agent, reason=RejectionReason.objects.get(code="incomplete_form"))
    Application.objects.filter(pk=app.pk).update(decided_at=timezone.now() - timedelta(days=800))
    AccessLog.objects.create(user=agent, method="GET", path="/old/")
    AccessLog.objects.filter(path="/old/").update(at=timezone.now() - timedelta(days=400))
    run = run_retention()
    app.refresh_from_db()
    assert run.results["rejected_applications"] == 1 and app.anonymised_at and app.last_name == "" and app.trn == ""
    assert not AccessLog.objects.filter(path="/old/").exists()
    approved.refresh_from_db()
    assert approved.last_name == "Campbell"


def test_privacy_pages_render(client, dpo):
    login(client, dpo)
    for url in ["/privacy/", "/privacy/requests/", "/privacy/breaches/", "/privacy/register/"]:
        assert client.get(url).status_code == 200, url
    assert b"TRN validation" in client.get("/privacy/register/").content
