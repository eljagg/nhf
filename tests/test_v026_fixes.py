"""v0.2.6 fixes."""

import re

import pytest
from django.test import override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
@pytest.mark.parametrize("fixture", ["agent", "manager", "ict"])
def test_continue_after_backup_codes_goes_somewhere_real(client, fixture, request):
    user = request.getfixturevalue(fixture)
    assert client.login(username=user.username, password=PASSWORD)
    client.get("/accounts/mfa/setup/")
    device = TOTPDevice.objects.get(user=user, confirmed=False)
    client.post("/accounts/mfa/setup/", {"token": f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"})
    page = client.get("/accounts/mfa/backup-codes/").content.decode()
    href = re.search(r'href="([^"]+)"[^>]*>I have saved them', page).group(1)
    assert href.startswith("/") and ":" not in href, href  # a path, never a route name like core:home
    assert client.get(href).status_code == 200


# --- ID issue and expiry tracking -------------------------------------------------------------------
def _member(agent, doctor, run_commits):
    from datetime import date

    from apps.members import services

    from .test_counter_journey import complete, start

    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    with run_commits():
        return services.approve(app.pk, user=agent).member


def test_member_id_document_saved_encrypted_with_dates(client, agent, doctor, taj, run_commits):
    from django.db import connection

    m = _member(agent, doctor, run_commits)
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.post(
        f"/members/{m.member_number}/",
        {"action": "iddoc", "d-id_type": "nids", "d-id_number": "123 456 789", "d-id_issue_date": "2020-01-15", "d-id_expiry": "2030-01-15"},
    )
    assert resp.status_code == 302
    m.refresh_from_db()
    assert m.id_number == "123 456 789" and str(m.id_expiry) == "2030-01-15" and m.id_checked_at
    with connection.cursor() as cur:
        cur.execute("SELECT id_number FROM members_member WHERE id=%s", [m.pk])
        assert "123" not in cur.fetchone()[0]


def test_member_id_dates_validated(client, agent, doctor, taj, run_commits):
    m = _member(agent, doctor, run_commits)
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.post(
        f"/members/{m.member_number}/",
        {"action": "iddoc", "d-id_type": "nids", "d-id_number": "1", "d-id_issue_date": "2030-01-15", "d-id_expiry": "2020-01-15"},
    )
    assert resp.status_code == 200 and "cannot be in the future" in resp.content.decode()


def test_expired_member_id_banner_list_and_digest(client, agent, supervisor_user, doctor, taj, run_commits):
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.idexpiry import check_id_expiry
    from apps.core.models import Notification
    from apps.members.models import Member

    m = _member(agent, doctor, run_commits)
    Member.objects.filter(pk=m.pk).update(id_type="drivers", id_expiry=timezone.localdate() - timedelta(days=3))
    assert client.login(username=agent.username, password=PASSWORD)
    assert "The ID on file has expired" in client.get(f"/members/{m.member_number}/").content.decode()
    assert m.member_number in client.get("/members/expired-ids/").content.decode()
    result = check_id_expiry()
    assert result["members_expired"] == 1
    assert Notification.objects.filter(template="member-ids-digest", recipient_user=supervisor_user).exists()
    check_id_expiry()
    assert Notification.objects.filter(template="member-ids-digest").count() == 1  # once a day


def test_staff_id_expiry_tells_the_person_and_administrators(agent, ict):
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.idexpiry import check_id_expiry
    from apps.core.models import Notification

    agent.id_type, agent.id_expiry = "drivers", timezone.localdate() + timedelta(days=10)
    agent.save()
    check_id_expiry()
    assert Notification.objects.filter(template="staff-id-expiry", recipient_user=agent).exists()
    assert Notification.objects.filter(template="staff-ids-digest", recipient_user=ict).exists()
    check_id_expiry()
    assert Notification.objects.filter(template="staff-id-expiry", recipient_user=agent).count() == 1  # not repeated within a week


def test_staff_issue_date_after_expiry_rejected(client, ict, agent):
    from .test_v023_security_fixes import login_verified

    login_verified(client, ict)
    data = {
        "first_name": "C",
        "last_name": "A",
        "email": agent.email,
        "job_title": "",
        "phone": "",
        "staff_number": "",
        "centre": agent.centre_id,
        "id_type": "nids",
        "id_number": "1",
        "id_issue_date": "2025-05-01",
        "id_expiry": "2024-05-01",
    }
    resp = client.post(f"/accounts/staff/{agent.pk}/", data)
    assert resp.status_code == 200 and "must be after the issue date" in resp.content.decode()


@pytest.fixture
def supervisor_user(centre):
    from .conftest import make_user

    return make_user("sup.test", "supervisor", "customer_care", centre=centre)


def test_demo_identity_filler_gives_everyone_a_unique_valid_nis(agent, doctor, taj, run_commits):
    import random

    from apps.core.management.commands.seed_demo_data import Command
    from apps.members.identifiers import is_valid_nis
    from apps.members.models import Member

    _member(agent, doctor, run_commits)
    Member.objects.update(nis_number="", id_type="")
    Command()._identity_details(random.Random(1))
    nis = list(Member.objects.values_list("nis_number", flat=True))
    assert nis and all(is_valid_nis(n) for n in nis) and len(set(nis)) == len(nis)
    assert not Member.objects.filter(id_type="").exists()


# --- v0.2.7: centre scoping -----------------------------------------------------------------------
def _app_at(agent, run_commits, centre_code, trn="100200301"):
    from datetime import date

    from apps.core.models import Centre
    from apps.members.models import Application

    from .test_counter_journey import start

    app = start(agent, run_commits, trn, "Marcia", "Campbell", date(1979, 3, 14))
    Application.objects.filter(pk=app.pk).update(centre=Centre.objects.get(code=centre_code))
    app.refresh_from_db()
    return app


def test_counter_staff_list_only_their_centre(client, agent, taj, run_commits):
    mbj = _app_at(agent, run_commits, "MBJ")
    hwt = _app_at(agent, run_commits, "HWT", trn="100200303")
    assert client.login(username=agent.username, password=PASSWORD)
    body = client.get("/members/applications/").content.decode()
    assert hwt.tracking_number in body and mbj.tracking_number not in body


def test_other_centre_application_is_read_only(client, agent, taj, run_commits):
    mbj = _app_at(agent, run_commits, "MBJ")
    assert client.login(username=agent.username, password=PASSWORD)
    page = client.get(f"/members/applications/{mbj.tracking_number}/")
    assert page.status_code == 200 and "belongs to" in page.content.decode() and not page.context["can_process"]
    assert client.post(f"/members/applications/{mbj.tracking_number}/approve/").status_code == 403
    mbj.refresh_from_db()
    assert mbj.worked_by_id is None  # no work lock taken from another centre


def test_assignment_lets_staff_work_another_centre(client, agent, manager, taj, run_commits):
    from apps.members.models import Application

    mbj = _app_at(agent, run_commits, "MBJ")
    Application.objects.filter(pk=mbj.pk).update(assigned_to=agent)
    assert client.login(username=agent.username, password=PASSWORD)
    page = client.get(f"/members/applications/{mbj.tracking_number}/")
    assert page.context["can_process"] and mbj.tracking_number in client.get("/members/applications/").content.decode()


def test_managers_see_every_centre(client, agent, manager, taj, run_commits):
    from .test_v023_security_fixes import login_verified

    mbj = _app_at(agent, run_commits, "MBJ")
    login_verified(client, manager)
    assert mbj.tracking_number in client.get("/members/applications/").content.decode()


def test_members_stay_searchable_island_wide(client, agent, doctor, taj, run_commits):
    from apps.core.models import Centre
    from apps.members.models import Member

    m = _member(agent, doctor, run_commits)
    Member.objects.filter(pk=m.pk).update(collection_centre=Centre.objects.get(code="MBJ"), registered_centre=Centre.objects.get(code="MBJ"))
    assert client.login(username=agent.username, password=PASSWORD)
    assert client.get(f"/members/{m.member_number}/").status_code == 200


def test_print_queue_cannot_be_widened_by_centre_bound_staff(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.get("/cards/queue/?centre=all")
    assert resp.status_code == 200
    assert all(c.centre_id == agent.centre_id for c in resp.context["page"])


def test_nis_default_is_letter_and_six_digits():
    from apps.members.identifiers import is_valid_nis

    assert is_valid_nis("G721675") and not is_valid_nis("123456789") and not is_valid_nis("G72167")
