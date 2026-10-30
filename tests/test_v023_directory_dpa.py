"""v0.2.3: AD account state followed during the session; Data Protection Act additions."""

from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models import AuditEvent, Parameter, StoredImage
from apps.directory import ldap
from apps.directory.models import GroupMapping
from apps.directory.services import sync_ad_users
from apps.members import services
from apps.privacy import services as privacy
from apps.privacy.models import Breach, DataSubjectRequest, ImpactAssessment, ProcessingActivity

from .conftest import PASSWORD
from .test_counter_journey import complete, start

pytestmark = pytest.mark.django_db
LDAP_MOCK = {
    "ENABLED": True,
    "SERVER_URI": "mock://demo",
    "BIND_DN": "",
    "BIND_PASSWORD": "",
    "USER_SEARCH_BASE": "",
    "GROUP_SEARCH_BASE": "",
    "USER_FILTER": "(&(objectClass=user)(sAMAccountName={username}))",
    "NESTED_GROUPS": True,
    "CA_CERT_FILE": "",
    "TIMEOUT": 5,
    "ALLOW_PLAIN": False,
}


def login_verified(client, user):
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    assert client.login(username=user.username, password=PASSWORD)
    assert (
        client.post("/accounts/mfa/verify/", {"token": f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"}).status_code == 302
    )


# --- 1. Active Directory state followed during the session ------------------------------------
@override_settings(LDAP=LDAP_MOCK)
def test_signed_in_ad_user_is_signed_out_when_access_is_removed_in_ad(client):
    assert client.login(username="ad.richards", password=ldap._demo_password())
    assert client.get("/").status_code == 200
    GroupMapping.objects.filter(group="NHF-MRS-CustomerCare").delete()  # same effect as removing her from the AD group
    session = client.session
    session["directory_checked_at"] = 0
    session.save()
    resp = client.get("/")
    assert resp.status_code == 302 and "revoked=1" in resp["Location"]
    user = get_user_model().objects.get(username="ad.richards")
    assert not user.is_active and user.deactivated_at is not None
    assert AuditEvent.objects.filter(action="directory.user_disabled").exists()
    assert "no longer enabled" in client.get(resp["Location"]).content.decode()


@override_settings(LDAP=LDAP_MOCK)
def test_recheck_waits_for_the_interval(client):
    assert client.login(username="ad.richards", password=ldap._demo_password())
    client.get("/")  # first check stamps the session
    GroupMapping.objects.filter(group="NHF-MRS-CustomerCare").delete()
    assert client.get("/").status_code == 200  # within 15 minutes: not re-checked yet
    assert get_user_model().objects.get(username="ad.richards").is_active


@override_settings(LDAP=LDAP_MOCK)
def test_directory_outage_does_not_sign_people_out(client, settings):
    assert client.login(username="ad.richards", password=ldap._demo_password())
    settings.LDAP = {**LDAP_MOCK, "SERVER_URI": "ldap://dc.unreachable.invalid"}  # refused: plain LDAP → DirectoryError
    session = client.session
    session["directory_checked_at"] = 0
    session.save()
    assert client.get("/").status_code == 200


@override_settings(LDAP=LDAP_MOCK)
def test_reenabled_in_ad_signs_in_again_but_portal_suspension_still_blocks(client):
    pw = ldap._demo_password()
    assert client.login(username="ad.richards", password=pw)
    user = get_user_model().objects.get(username="ad.richards")
    get_user_model().objects.filter(pk=user.pk).update(is_active=False, deactivated_by_directory=True)
    client.logout()
    assert client.login(username="ad.richards", password=pw)  # AD enables her again → reactivated
    user.refresh_from_db()
    assert user.is_active and user.deactivated_at is None
    user.suspended_at = timezone.now()
    user.save()
    client.logout()
    resp = client.post("/accounts/login/", {"username": "ad.richards", "password": pw})
    assert "suspended" in resp.content.decode()


@override_settings(LDAP=LDAP_MOCK)
def test_sync_stops_when_directory_unreachable(settings):
    get_user_model().objects.create(username="ad.someone", source="ad", is_active=True)
    settings.LDAP = {**LDAP_MOCK, "SERVER_URI": "ldap://x.invalid"}
    result = sync_ad_users()
    assert result["unreachable"] == 1 and result["disabled"] == 0
    assert get_user_model().objects.get(username="ad.someone").is_active


def test_disabled_directory_account_shown_as_such(client, ict):
    get_user_model().objects.create(username="ad.leaver", source="ad", is_active=False)
    login_verified(client, ict)
    assert "Disabled in directory" in client.get("/accounts/staff/?state=disabled").content.decode()


# --- 2. Data Protection Act --------------------------------------------------------------------
def test_restriction_blocks_approval_until_lifted(agent, doctor, taj, run_commits, dpo_user):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    change = app
    change.refresh_from_db()
    privacy.restrict_processing(member, reason="Disputes recorded condition", user=dpo_user)
    findings = services.evaluate(change).findings
    assert any(f.rule == "DPA" and f.level == "error" for f in findings)
    privacy.lift_restriction(member, note="Resolved", user=dpo_user)
    change.refresh_from_db()
    assert not any(f.rule == "DPA" for f in services.evaluate(change).findings)
    assert AuditEvent.objects.filter(action="privacy.processing_restricted").exists()


@pytest.fixture
def dpo_user(centre):
    from .conftest import make_user

    return make_user("dpo.test", "dpo", centre=centre)


def test_dsr_restrict_action_and_member_banner(client, dpo_user, agent, doctor, taj, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    dsr = DataSubjectRequest.objects.create(requester_name="Marcia Campbell", kind="objection", member=member, due_at=timezone.now() + timedelta(days=30))
    login_verified(client, dpo_user)
    client.post(f"/privacy/requests/{dsr.pk}/", {"restrict": "1", "reason": "Objects to sharing with card production"})
    member.refresh_from_db()
    assert member.processing_restricted_at and dsr.reference in member.processing_restriction_reason
    client.logout()
    assert client.login(username=agent.username, password=PASSWORD)
    assert "Processing restricted" in client.get(f"/members/{member.member_number}/").content.decode()


def test_new_request_kinds_exist():
    kinds = dict(DataSubjectRequest.KINDS)
    assert "automated" in kinds and "marketing" in kinds


def test_breach_notices_contain_what_the_act_requires(client, dpo_user):
    Parameter.objects.update_or_create(key="dpo-name", defaults={"value": "Simone Grant"})
    Parameter.objects.update_or_create(key="dpo-email", defaults={"value": "dpo@nhf.example"})
    b = Breach.objects.create(
        title="Lost laptop",
        description="Unencrypted export on a lost laptop",
        data_categories="names, TRNs",
        subjects_affected=40,
        likely_consequences="Identity fraud risk",
        actions="Remote wipe requested",
    )
    login_verified(client, dpo_user)
    text = client.get(f"/privacy/breaches/{b.pk}/notice/commissioner.txt").content.decode()
    for part in (
        "Facts of the breach",
        "Nature and scale",
        "40",
        "Likely consequences",
        "Identity fraud risk",
        "Remote wipe",
        "Simone Grant",
        "dpo@nhf.example",
    ):
        assert part in text
    letter = client.get(f"/privacy/breaches/{b.pk}/notice/subjects.txt").content.decode()
    assert "Information Commissioner" in letter and "Simone Grant" in letter
    assert client.get(f"/privacy/breaches/{b.pk}/notice/other.txt").status_code == 404


def test_subjects_notice_overdue_after_window():
    b = Breach.objects.create(title="x", description="x", data_categories="x", subjects_affected=3, discovered_at=timezone.now() - timedelta(hours=80))
    assert b.subjects_notice_overdue


def test_annual_impact_assessment_draft_approve_submit(client, dpo_user):
    login_verified(client, dpo_user)
    client.post("/privacy/impact-assessments/", {"start": "1"})
    year = timezone.localdate().year
    dpia = ImpactAssessment.objects.get(year=year)
    assert "Member registration and eligibility" in dpia.scope and "Two-step sign-in" in dpia.measures
    client.post(f"/privacy/impact-assessments/{year}/", {"action": "approve"})
    client.post(f"/privacy/impact-assessments/{year}/", {"action": "submitted"})
    dpia.refresh_from_db()
    assert dpia.status == "submitted" and dpia.submitted_at
    client.post(f"/privacy/impact-assessments/{year}/", {"action": "save", "scope": "changed", "risks": "r", "measures": "m", "residual_risk": "low"})
    dpia.refresh_from_db()
    assert dpia.scope != "changed"  # locked once submitted


def test_dashboard_shows_registration_and_dpia_status(client, dpo_user):
    login_verified(client, dpo_user)
    body = client.get("/privacy/").content.decode()
    assert "Registration number not set" in body and "Not started" in body
    Parameter.objects.update_or_create(key="dpa-registration-number", defaults={"value": "DC-2024-00123"})
    Parameter.objects.update_or_create(key="dpa-registration-expiry", defaults={"value": (date.today() + timedelta(days=200)).isoformat()})
    body = client.get("/privacy/").content.decode()
    assert "DC-2024-00123" in body and "Registered" in body


def test_former_staff_id_records_erased_after_retention(ict):
    from apps.core import images

    from .conftest import make_user
    from .test_v022_practitioners_staff import jpeg

    leaver = make_user("cc.leaver", "customer_care")
    leaver.id_number, leaver.id_type = "123456789", "nids"
    leaver.id_document = images.store(jpeg(), "staff_id")
    leaver.photo = images.store(jpeg(), "staff_photo")
    leaver.is_active = False
    leaver.save()
    assert leaver.deactivated_at
    get_user_model().objects.filter(pk=leaver.pk).update(deactivated_at=timezone.now() - timedelta(days=400))
    assert privacy.retention_candidates()["staff_id_records"].count() == 1
    privacy.run_retention(user=ict)
    leaver.refresh_from_db()
    assert leaver.id_number == "" and leaver.id_document is None and leaver.photo is None
    assert not StoredImage.objects.exists()
    assert AuditEvent.objects.filter(action="privacy.staff_identity_erased").exists()


def test_bootstrap_upgrades_untouched_notice_and_adds_activities():
    old_text = "The National Health Fund collects your personal details and the medical conditions certified by your doctor to register you for NHF benefits, produce your NHF Card and process your benefit claims. Your information is shared only with the Tax Administration (TRN validation), the Medical Council (doctor confirmation), the claims adjudicator and card production, and is kept in line with the Fund's retention policy. You may ask for a copy of your information or for it to be corrected."
    Parameter.objects.filter(key="privacy-notice-text").update(value=old_text)
    Parameter.objects.filter(key="privacy-notice-version").update(value="2026-10")
    Parameter.objects.filter(key="dsr-days").update(value=21)  # NHF's own edit must survive
    call_command("bootstrap_reference", verbosity=0)
    assert "restrict" in Parameter.get("privacy-notice-text") and Parameter.get("privacy-notice-version") == "2026-11"
    assert Parameter.get("dsr-days") == 21
    assert ProcessingActivity.objects.filter(name__in=["Nurse validation", "Staff identity records", "Directory sign-in"]).count() == 3
