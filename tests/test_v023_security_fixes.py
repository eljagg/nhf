"""Regression tests for the v0.2.3 security review findings."""

import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from apps.core import csvsafe
from apps.core.models import AuditEvent
from apps.core.net import client_ip
from apps.security.models import AccessLog, SecurityAlert

from .conftest import PASSWORD, make_user

pytestmark = pytest.mark.django_db


def code(device):
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"


def login_verified(client, user):
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first() or TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    assert client.login(username=user.username, password=PASSWORD)
    assert client.post("/accounts/mfa/verify/", {"token": code(device)}).status_code == 302
    return device


# 1. Stolen password cannot enrol a new authenticator
@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_mfa_setup_requires_existing_factor_first(client, agent):
    victim_device = TOTPDevice.objects.create(user=agent, name="phone", confirmed=True)
    StaticDevice.objects.create(user=agent, name="Backup codes", confirmed=True).token_set.create(token="keepme12")
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.get("/accounts/mfa/setup/")
    assert resp.status_code == 302 and "/accounts/mfa/verify/" in resp["Location"]
    assert client.post("/accounts/mfa/setup/", {"token": "123456"}).status_code == 302
    assert list(TOTPDevice.objects.filter(user=agent)) == [victim_device]
    assert StaticDevice.objects.get(user=agent).token_set.filter(token="keepme12").exists()


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_verified_user_can_replace_phone_and_old_one_stops_working(client, agent):
    old = login_verified(client, agent)
    client.get("/accounts/mfa/setup/")
    new = TOTPDevice.objects.get(user=agent, confirmed=False)
    client.post("/accounts/mfa/setup/", {"token": code(new)})
    assert list(TOTPDevice.objects.filter(user=agent).values_list("pk", flat=True)) == [new.pk]
    assert not TOTPDevice.objects.filter(pk=old.pk).exists()


# 2. Separation of duties
def test_cannot_grant_yourself_a_temporary_role(client, ict, manager):
    login_verified(client, ict)
    resp = client.get("/accounts/temporary-roles/")
    form = resp.context["form"]
    assert ict not in form.fields["user"].queryset
    assert [c[0] for c in form.fields["role"].choices] == ["back_office"]
    client.post("/accounts/temporary-roles/", {"user": ict.pk, "role": "manager", "hours": 8, "reason": "x"})
    client.post("/accounts/temporary-roles/", {"user": manager.pk, "role": "ict_admin", "hours": 8, "reason": "x"})
    from apps.accounts.models import TemporaryRole

    assert not TemporaryRole.objects.exists()


def test_manager_cannot_grant_privileged_roles(client, manager, agent):
    login_verified(client, manager)
    choices = [c[0] for c in client.get("/accounts/temporary-roles/").context["form"].fields["role"].choices]
    assert "supervisor" in choices and not {"manager", "ict_admin", "db_admin", "dpo"} & set(choices)


def test_admin_cannot_edit_own_account_or_superuser_flag(client, ict, agent):
    ict.is_staff = True
    ict.save()
    login_verified(client, ict)
    assert (
        client.get(f"/backoffice/accounts/user/{ict.pk}/change/").status_code in (302, 403)
        or "readonly" in client.get(f"/backoffice/accounts/user/{ict.pk}/change/").content.decode()
    )
    page = client.get(f"/backoffice/accounts/user/{agent.pk}/change/").content.decode()
    assert 'name="is_superuser"' not in page and 'name="user_permissions"' not in page


def test_admin_cannot_set_password_of_privileged_account(client, ict, manager):
    ict.is_staff = True
    ict.save()
    login_verified(client, ict)
    assert client.get(f"/backoffice/accounts/user/{manager.pk}/password/").status_code == 403


def test_back_office_cannot_change_roles(client, ict, agent):
    ict.is_staff = True
    ict.save()
    login_verified(client, ict)
    page = client.get(f"/backoffice/accounts/user/{agent.pk}/change/").content.decode()
    assert 'name="groups"' not in page


def test_role_change_needs_request_and_a_different_manager(client, ict, manager, agent):
    from apps.accounts.models import RoleChangeRequest

    login_verified(client, ict)
    client.post(f"/accounts/staff/{agent.pk}/role-request/", {"action": "add", "role": "supervisor", "reason": "Promotion letter 88"})
    req = RoleChangeRequest.objects.get(target=agent)
    assert req.status == "pending" and "supervisor" not in agent.groups.values_list("name", flat=True)
    client.post(f"/accounts/role-requests/{req.pk}/decide/", {"decision": "approve"})  # requester cannot approve
    req.refresh_from_db()
    assert req.status == "pending"
    client.logout()
    login_verified(client, manager)
    client.post(f"/accounts/role-requests/{req.pk}/decide/", {"decision": "approve", "note": "ok"})
    req.refresh_from_db()
    assert req.status == "approved" and agent.groups.filter(name="supervisor").exists()
    assert AuditEvent.objects.filter(action="security.role_change_approved").exists()


def test_manager_cannot_approve_own_promotion(client, ict, manager):
    from apps.accounts.models import RoleChangeRequest

    req = RoleChangeRequest.objects.create(target=manager, role="db_admin", action="add", reason="x", requested_by=ict)
    login_verified(client, manager)
    client.post(f"/accounts/role-requests/{req.pk}/decide/", {"decision": "approve"})
    req.refresh_from_db()
    assert req.status == "pending"


def test_directory_accounts_get_roles_from_ad_not_requests(client, ict):
    from apps.accounts.models import RoleChangeRequest

    ad_user = get_user_model().objects.create(username="ad.x", source="ad")
    login_verified(client, ict)
    client.post(f"/accounts/staff/{ad_user.pk}/role-request/", {"action": "add", "role": "manager", "reason": "x"})
    assert not RoleChangeRequest.objects.exists()


def test_parameter_floor_cannot_switch_off_access_log(client, settings):
    from apps.core.models import Parameter

    Parameter.objects.update_or_create(key="access-log-retention-days", defaults={"value": 0})
    assert Parameter.get("access-log-retention-days") == 180


def test_back_office_user_cannot_edit_security_parameters(client, centre):
    from apps.core.models import Parameter

    bo = make_user("bo.user", "back_office", centre=centre)
    bo.is_staff = True
    bo.save()
    p = Parameter.objects.get(key="access-log-retention-days")
    assert client.login(username=bo.username, password=PASSWORD)
    assert (
        client.get(f"/backoffice/core/parameter/{p.pk}/change/").status_code in (302, 403)
        or 'name="value"' not in client.get(f"/backoffice/core/parameter/{p.pk}/change/").content.decode()
    )


def test_undecryptable_value_is_never_overwritten(settings, agent):
    from cryptography.fernet import Fernet
    from django.db import connection

    from apps.core.crypto import Undecryptable

    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEY = k1
    settings.FIELD_ENCRYPTION_LEGACY_FALLBACK = False
    agent.id_number = "123456789"
    agent.save()
    with connection.cursor() as cur:
        cur.execute("SELECT id_number FROM accounts_user WHERE id=%s", [agent.pk])
        token = cur.fetchone()[0]
    settings.FIELD_ENCRYPTION_KEY = k2  # wrong key
    fresh = get_user_model().objects.get(pk=agent.pk)
    assert isinstance(fresh.id_number, Undecryptable) and fresh.id_number == ""
    fresh.job_title = "changed"
    fresh.save()
    with connection.cursor() as cur:
        cur.execute("SELECT id_number FROM accounts_user WHERE id=%s", [agent.pk])
        assert cur.fetchone()[0] == token  # kept
    settings.FIELD_ENCRYPTION_KEY = k1
    assert get_user_model().objects.get(pk=agent.pk).id_number == "123456789"


def test_rotate_command_is_all_or_nothing(settings, agent):
    from cryptography.fernet import Fernet
    from django.core.management import CommandError, call_command

    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_LEGACY_FALLBACK = False
    settings.FIELD_ENCRYPTION_KEY = k1
    agent.id_number = "999888777"
    agent.save()
    settings.FIELD_ENCRYPTION_KEY = k2  # old key missing
    with pytest.raises(CommandError):
        call_command("rotate_field_keys")
    settings.FIELD_ENCRYPTION_KEY = f"{k2},{k1}"
    call_command("rotate_field_keys")
    settings.FIELD_ENCRYPTION_KEY = k2
    assert get_user_model().objects.get(pk=agent.pk).id_number == "999888777"


def test_sync_holds_mass_disable(settings):
    from apps.directory.models import GroupMapping
    from apps.directory.services import sync_ad_users

    settings.LDAP = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo"}
    for name in ("ad.campbell", "ad.richards", "ad.henry", "ad.auditor"):
        get_user_model().objects.create(username=name, source="ad", is_active=True)
    GroupMapping.objects.all().delete()  # everyone would lose access: looks like misconfiguration
    result = sync_ad_users()
    assert result["held"] == 4 and result["disabled"] == 0
    assert get_user_model().objects.filter(source="ad", is_active=True).count() == 4
    assert SecurityAlert.objects.filter(kind="directory", severity="high").exists()


def test_wrong_search_base_is_treated_as_unreachable(settings):
    from apps.directory import ldap

    settings.LDAP = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo", "USER_SEARCH_BASE": "OU=Empty,DC=demo,DC=nhf,DC=local"}
    with pytest.raises(ldap.DirectoryError):
        ldap.lookup("ad.campbell")


# 3. E-mail of privileged accounts protected on the Staff page
def test_manager_cannot_redirect_admin_email(client, manager, ict):
    login_verified(client, manager)
    data = {
        "first_name": "I",
        "last_name": "A",
        "email": "attacker@evil.example",
        "job_title": "",
        "phone": "",
        "staff_number": "",
        "centre": "",
        "id_type": "",
        "id_number": "",
        "id_expiry": "",
    }
    client.post(f"/accounts/staff/{ict.pk}/", data)
    ict.refresh_from_db()
    assert ict.email != "attacker@evil.example"


def test_email_change_on_ordinary_account_is_audited_and_old_address_told(client, ict, agent, mailoutbox):
    login_verified(client, ict)
    old = agent.email
    data = {
        "first_name": "C",
        "last_name": "A",
        "email": "new@x.invalid",
        "job_title": "",
        "phone": "",
        "staff_number": "",
        "centre": agent.centre_id,
        "id_type": "",
        "id_number": "",
        "id_expiry": "",
    }
    client.post(f"/accounts/staff/{agent.pk}/", data)
    assert AuditEvent.objects.filter(action="staff.email_changed").exists()
    assert any(old in m.to for m in mailoutbox)


# 4. OIDC open redirect
def test_oidc_next_cannot_leave_the_site():
    from django.utils.http import url_has_allowed_host_and_scheme

    assert not url_has_allowed_host_and_scheme("/\\evil.com", allowed_hosts={"testserver"})


# 5. Client address
@override_settings(TRUSTED_PROXY_COUNT=1)
def test_client_ip_takes_the_proxy_entry_not_the_forged_one():
    rf = RequestFactory()
    req = rf.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9", REMOTE_ADDR="10.0.0.2")
    assert client_ip(req) == "203.0.113.9"
    req = rf.get("/", HTTP_X_FORWARDED_FOR="x", REMOTE_ADDR="10.0.0.2")
    assert client_ip(req) == "10.0.0.2"


@override_settings(TRUSTED_PROXY_COUNT=1)
def test_garbage_forwarded_header_still_writes_access_log(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    client.get("/doctors/", HTTP_X_FORWARDED_FOR="not-an-ip")
    assert AccessLog.objects.filter(user=agent, path="/doctors/").exists()


# 6. Demo mode
def test_prod_settings_default_demo_mode_off(monkeypatch):
    import importlib
    import sys

    monkeypatch.setenv("SECRET_KEY", "x" * 60)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "SsAb6V9MjT94CAQh-umE92Inpk784U83WCELZXCnLkU=")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    sys.modules.pop("config.settings.prod", None)
    prod = importlib.import_module("config.settings.prod")
    assert prod.DEMO_MODE is False and prod.TRUSTED_PROXY_COUNT == 1


def test_mock_directory_refused_outside_demo_mode(settings):
    from apps.directory import ldap

    settings.DEMO_MODE = False
    settings.LDAP = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo"}
    with pytest.raises(ldap.DirectoryError):
        ldap.authenticate("ad.campbell", "x")


def test_seed_refuses_outside_demo_mode(settings, capsys):
    from django.core.management import call_command

    settings.DEMO_MODE = False
    call_command("seed_demo_data", "--force")
    assert "never seeded" in capsys.readouterr().out
    assert not get_user_model().objects.filter(username="cc.walker").exists()


# 7. Field key
def test_prod_refuses_to_start_without_field_key(monkeypatch):
    import importlib
    import sys

    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("SECRET_KEY", "x" * 60)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "")
    sys.modules.pop("config.settings.prod", None)
    with pytest.raises(ImproperlyConfigured):
        importlib.import_module("config.settings.prod")
    sys.modules.pop("config.settings.prod", None)


def test_key_rotation_keeps_old_values_readable(settings):
    from cryptography.fernet import Fernet

    from apps.core.crypto import decrypt, encrypt

    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.FIELD_ENCRYPTION_KEY = old
    token = encrypt("100200301")
    settings.FIELD_ENCRYPTION_KEY = f"{new},{old}"
    assert decrypt(token) == "100200301"
    settings.FIELD_ENCRYPTION_KEY = new
    assert decrypt(token) == ""


# 8. Admin lock enforced on live sessions; admin-disabled AD account stays disabled
def test_locked_account_is_signed_out_on_next_request(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    get_user_model().objects.filter(pk=agent.pk).update(locked_until=timezone.now() + timedelta(hours=1))
    assert "/accounts/login/" in client.get("/")["Location"]


def test_directory_does_not_reenable_admin_disabled_account(settings, client):
    from apps.directory import ldap

    settings.LDAP = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo"}
    assert client.login(username="ad.campbell", password=ldap._demo_password())
    user = get_user_model().objects.get(username="ad.campbell")
    user.is_active = False
    user.save()  # disabled by an administrator here
    client.logout()
    assert not client.login(username="ad.campbell", password=ldap._demo_password())
    user.refresh_from_db()
    assert not user.is_active


# 10. API schema not public
def test_api_schema_requires_sign_in(client):
    assert client.get("/api/schema/").status_code in (401, 403)


# 11. Absolute session cap
def test_absolute_session_cap(client, agent, settings):
    assert client.login(username=agent.username, password=PASSWORD)
    client.get("/")
    s = client.session
    s["login_at"] = int(timezone.now().timestamp()) - settings.SESSION_COOKIE_AGE - 10
    s.save()
    assert "/accounts/login/" in client.get("/")["Location"]


# 12. Outbound messages hidden from application administrators
def test_ict_admin_does_not_see_outbound_sms(client, ict):
    login_verified(client, ict)
    assert client.get("/inbox/").context["outbound"] == []


# 13. CSV formula injection
def test_csv_cells_are_neutralised():
    assert csvsafe.row(["=HYPERLINK(1)", "+1", "@x", "ok", None]) == ["'=HYPERLINK(1)", "'+1", "'@x", "ok", ""]
    assert csvsafe.filename('a"b/c') == "a_b_c"


# 14. DSR member lookup
def test_dsr_lookup_ignores_junk(agent):
    from apps.privacy.views import _find_member

    assert _find_member("-") is None and _find_member("12") is None


# 15. Image size limits
def test_huge_image_refused_before_decoding(client, agent):
    img = Image.new("1", (8000, 5000))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.post("/accounts/me/photo/", {"image": SimpleUploadedFile("big.png", buf.getvalue(), content_type="image/png")}, follow=True)
    assert "too large" in resp.content.decode()


def test_oversized_request_body_refused(client):
    resp = client.generic("POST", "/accounts/login/", b"x", CONTENT_LENGTH=str(30 * 1024 * 1024), content_type="application/octet-stream")
    assert resp.status_code == 413


# 16. Lookup limits
def test_trn_screening_limited_per_user(client, agent):
    from django.core.cache import cache

    from apps.core.models import Parameter

    cache.clear()
    Parameter.objects.update_or_create(key="limit-trn-screen-per-hour", defaults={"value": 5})
    assert client.login(username=agent.username, password=PASSWORD)
    for _ in range(5):
        client.get("/identity/screen/?number=100200301")
    resp = client.get("/identity/screen/?number=100200301", follow=True)
    assert "hourly limit" in resp.content.decode()
    assert SecurityAlert.objects.filter(kind="rate_limit", user=agent).exists()
    cache.clear()


# 18. Headers
def test_security_headers_present(client, agent):
    assert client.login(username=agent.username, password=PASSWORD)
    resp = client.get("/")
    assert "camera=()" in resp["Permissions-Policy"] and "no-store" in resp["Cache-Control"]


def test_backoffice_login_uses_staff_sign_in(client):
    resp = client.get("/backoffice/login/?next=/backoffice/")
    assert resp.status_code == 302 and resp["Location"].startswith("/accounts/login/")


def test_new_user_cannot_be_member_of_temp_role_self_grant_via_admin(client, ict):
    ict.is_staff = True
    ict.save()
    login_verified(client, ict)
    assert client.get("/backoffice/accounts/temporaryrole/add/").status_code == 403


def test_make_user_helper_available():
    assert make_user("x.y", "customer_care").username == "x.y"
