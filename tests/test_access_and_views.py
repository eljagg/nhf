"""Roles, temporary roles, need-to-know masking, work locks, search and page rendering."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import TemporaryRole
from apps.accounts.roles import has_role
from apps.members import services

from .conftest import PASSWORD
from .test_counter_journey import complete, start

pytestmark = pytest.mark.django_db


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def test_login_page_and_redirect(client):
    assert client.get("/").status_code == 302
    assert client.get("/accounts/login/").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}


def test_counter_pages_render_for_customer_care(client, agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    login(client, agent)
    for url in [
        "/",
        "/members/new/",
        "/members/applications/",
        f"/members/applications/{app.tracking_number}/",
        "/members/search/?q=100200301",
        "/intake/",
        "/cards/queue/",
        "/identity/screen/",
        "/identity/srn/",
        "/doctors/",
        "/inbox/",
    ]:
        assert client.get(url).status_code in (200, 302), url
    response = client.post(f"/members/applications/{app.tracking_number}/approve/")
    assert response.status_code == 302
    app.refresh_from_db()
    assert app.status == "approved"
    assert client.get(f"/members/{app.member.member_number}/").status_code == 200


def test_start_form_creates_application_and_redirects(client, agent, taj, django_capture_on_commit_callbacks):
    login(client, agent)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            "/members/new/",
            {
                "channel": "walk_in",
                "centre": agent.centre_id,
                "received_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M"),
                "trn": "100 200 301",
                "form_first_name": "Marcia",
                "form_last_name": "Campbell",
                "form_dob": "1979-03-14",
            },
        )
    assert response.status_code == 302 and "/members/applications/NHF-A-" in response.url


def test_auditor_reads_but_cannot_decide_and_conditions_are_masked(client, agent, auditor, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    member = services.approve(app.pk, user=agent).member
    login(client, auditor)
    page = client.get(f"/members/{member.member_number}/").content.decode()
    assert "details hidden for your role" in page and "Hypertension" not in page
    assert client.post(f"/members/applications/{app.tracking_number}/reject/", {"reason": 1}).status_code == 403
    assert client.get("/audit/").status_code == 200


def test_application_admin_has_no_member_access(client, ict, settings):
    settings.MFA_REQUIRED_ROLES = []  # MFA itself is covered by test_manager_must_enrol_mfa
    login(client, ict)
    assert client.get("/members/applications/").status_code == 403
    assert client.get("/accounts/temporary-roles/").status_code in (200, 302)


def test_temporary_role_grants_and_expires(manager, agent):
    assert not has_role(agent, "supervisor")
    grant = TemporaryRole.objects.create(
        user=agent, group=Group.objects.get(name="supervisor"), expires_at=timezone.now() + timedelta(hours=1), reason="Cover", granted_by=manager
    )
    fresh = type(agent).objects.get(pk=agent.pk)
    assert has_role(fresh, "supervisor")
    grant.expires_at = timezone.now() - timedelta(seconds=1)
    grant.save()
    assert not has_role(type(agent).objects.get(pk=agent.pk), "supervisor")


def test_manager_must_enrol_mfa(client, manager):
    login(client, manager)
    response = client.get("/")
    assert response.status_code == 302 and response.url == "/accounts/mfa/setup/"


def test_work_lock_blocks_second_agent(client, agent, agent2, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    login(client, agent)
    client.get(f"/members/applications/{app.tracking_number}/")
    client.logout()
    login(client, agent2)
    page = client.get(f"/members/applications/{app.tracking_number}/").content.decode()
    assert "is working on this record now" in page
    client.post(f"/members/applications/{app.tracking_number}/", {"phone_mobile": "876-000-0000"})
    app.refresh_from_db()
    assert app.phone_mobile == ""


def test_tracking_search_finds_by_each_key(client, agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    member = services.approve(app.pk, user=agent).member
    login(client, agent)
    assert client.get(f"/members/search/?q={app.tracking_number}").url.endswith(f"/members/applications/{app.tracking_number}/")
    assert client.get(f"/members/search/?q={member.member_number}").status_code in (200, 302)
    assert client.get("/members/search/?q=100200301").status_code in (200, 302)
    assert b"Campbell" in client.get("/members/search/?programme=nhf").content


def test_seed_demo_data_small(db):
    call_command("seed_demo_data", "--force", "--members", "200", verbosity=0)
    from apps.members.models import Application, Member

    assert Member.objects.count() == 200
    assert Application.objects.filter(channel="online").exists()
