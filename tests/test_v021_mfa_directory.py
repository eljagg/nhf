"""v0.2.1: two-step sign-in for every staff account, Active Directory over LDAPS, Entra ID single sign-on."""

import base64
import time
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.models import AuditEvent, Parameter
from apps.directory import ldap
from apps.directory.models import GroupMapping
from apps.directory.provisioning import DirectoryIdentity, NotAuthorised, provision
from apps.directory.services import sync_ad_users
from apps.security.models import SecurityAlert

from .conftest import PASSWORD, make_user

pytestmark = pytest.mark.django_db

LDAP_MOCK = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo"}


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def enrol(user):
    return TOTPDevice.objects.create(user=user, name="phone", confirmed=True)


def code_for(device):
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"


def login_verified(client, user):
    """Password, then a valid authenticator code (privileged roles always need the second step)."""
    device = TOTPDevice.objects.filter(user=user, confirmed=True).first() or enrol(user)
    login(client, user)
    assert client.post("/accounts/mfa/verify/", {"token": code_for(device)}).status_code == 302


# --- 1. Two-step sign-in for every staff account ------------------------------
@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_customer_care_must_enrol_when_mfa_is_required_for_all(client, agent):
    login(client, agent)
    resp = client.get("/")
    assert resp.status_code == 302 and "/accounts/mfa/setup/" in resp["Location"]


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_enrolled_user_is_sent_to_verify(client, agent):
    enrol(agent)
    login(client, agent)
    resp = client.get("/")
    assert resp.status_code == 302 and "/accounts/mfa/verify/" in resp["Location"]


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=True, DEMO_MODE=True)
def test_demo_switch_exempts_counter_staff_but_never_managers(client, agent, manager):
    login(client, agent)
    assert client.get("/").status_code == 200
    client.logout()
    login(client, manager)
    assert "/accounts/mfa/setup/" in client.get("/")["Location"]


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=True, DEMO_MODE=False)
def test_demo_switch_is_ignored_outside_demo_mode(client, agent):
    login(client, agent)
    assert "/accounts/mfa/setup/" in client.get("/")["Location"]


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_enrolment_issues_ten_backup_codes_shown_once(client, agent):
    login(client, agent)
    client.get("/accounts/mfa/setup/")
    device = TOTPDevice.objects.get(user=agent, confirmed=False)
    resp = client.post("/accounts/mfa/setup/", {"token": code_for(device)})
    assert resp.status_code == 302 and resp["Location"].endswith("/accounts/mfa/backup-codes/")
    page = client.get("/accounts/mfa/backup-codes/")
    assert page.status_code == 200
    codes = page.context["codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    assert StaticDevice.objects.get(user=agent).token_set.count() == 10
    assert client.get("/accounts/mfa/backup-codes/").status_code == 302  # shown once only


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_backup_code_signs_in_once_only(client, agent):
    from apps.accounts.views import issue_backup_codes

    enrol(agent)
    codes = issue_backup_codes(agent)
    login(client, agent)
    resp = client.post("/accounts/mfa/verify/", {"token": codes[0]})
    assert resp.status_code == 302
    assert client.get("/").status_code == 200
    assert StaticDevice.objects.get(user=agent).token_set.count() == 9
    client.logout()
    login(client, agent)
    again = client.post("/accounts/mfa/verify/", {"token": codes[0]})
    assert again.status_code == 200 and "Code not accepted" in again.content.decode()


@override_settings(MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_repeated_wrong_codes_raise_an_alert(client, agent):
    cache.clear()
    enrol(agent)
    login(client, agent)
    for _ in range(int(Parameter.get("alert-failed-mfa"))):
        client.post("/accounts/mfa/verify/", {"token": "000000"})
    assert SecurityAlert.objects.filter(kind="failed_mfa", user=agent).count() == 1


def test_admin_resets_another_users_two_step_but_not_their_own(client, ict, agent):
    from apps.accounts.views import issue_backup_codes

    enrol(agent)
    issue_backup_codes(agent)
    login_verified(client, ict)
    resp = client.post(f"/security/users/{agent.pk}/reset-mfa/", {"reason": "lost phone"})
    assert resp.status_code == 302
    assert not TOTPDevice.objects.filter(user=agent).exists() and not StaticDevice.objects.filter(user=agent).exists()
    assert SecurityAlert.objects.filter(kind="mfa_reset", user=agent).exists()
    assert AuditEvent.objects.filter(action="security.mfa_reset").exists()
    client.post(f"/security/users/{ict.pk}/reset-mfa/", {"reason": "self"})
    assert TOTPDevice.objects.filter(user=ict).exists()


def test_only_application_administrators_can_reset(client, manager, agent):
    enrol(agent)
    login_verified(client, manager)
    assert client.post(f"/security/users/{agent.pk}/reset-mfa/").status_code == 403
    assert TOTPDevice.objects.filter(user=agent).exists()


# --- 2. Active Directory --------------------------------------------------------
@override_settings(LDAP=LDAP_MOCK)
def test_directory_sign_in_creates_account_with_mapped_role_and_centre(client):
    assert client.login(username="ad.campbell", password=ldap._demo_password())
    user = get_user_model().objects.get(username="ad.campbell")
    assert user.source == "ad" and not user.has_usable_password()
    assert list(user.groups.values_list("name", flat=True)) == ["customer_care"]
    assert user.centre.code == "HWT"
    assert AuditEvent.objects.filter(action="directory.user_created").exists()


@override_settings(LDAP=LDAP_MOCK)
def test_directory_wrong_password_is_refused(client):
    assert not client.login(username="ad.campbell", password="wrong")
    assert not get_user_model().objects.filter(username="ad.campbell").exists()


@override_settings(LDAP=LDAP_MOCK)
def test_unmapped_and_disabled_directory_accounts_are_refused(client):
    resp = client.post("/accounts/login/", {"username": "ad.nogroup", "password": ldap._demo_password()})
    assert resp.status_code == 200 and "not in any group" in resp.content.decode()
    resp = client.post("/accounts/login/", {"username": "ad.disabled", "password": ldap._demo_password()})
    assert "disabled in the directory" in resp.content.decode()
    assert not get_user_model().objects.filter(username__in=["ad.nogroup", "ad.disabled"]).exists()


@override_settings(LDAP=LDAP_MOCK)
def test_local_account_is_never_taken_over_by_a_directory_name(client, centre):
    local = make_user("ad.henry", "customer_care", centre=centre)
    assert not client.login(username="ad.henry", password=ldap._demo_password())
    assert client.login(username="ad.henry", password=PASSWORD)
    local.refresh_from_db()
    assert local.source == "local" and local.has_usable_password()


@override_settings(LDAP=LDAP_MOCK)
def test_roles_follow_the_directory_at_each_sign_in(client):
    assert client.login(username="ad.henry", password=ldap._demo_password())
    user = get_user_model().objects.get(username="ad.henry")
    assert set(user.groups.values_list("name", flat=True)) == {"customer_care", "supervisor"}
    GroupMapping.objects.filter(group="NHF-MRS-Supervisors").delete()
    client.logout()
    assert client.login(username="ad.henry", password=ldap._demo_password())
    assert set(user.groups.values_list("name", flat=True)) == {"customer_care"}
    assert AuditEvent.objects.filter(action="directory.roles_changed").exists()


@override_settings(LDAP=LDAP_MOCK)
def test_nightly_sync_disables_accounts_that_lost_access(client):
    assert client.login(username="ad.richards", password=ldap._demo_password())
    ghost = get_user_model().objects.create(username="ad.left", source="ad", external_id="gone", is_active=True)
    GroupMapping.objects.filter(group="NHF-MRS-CustomerCare").delete()
    result = sync_ad_users()
    assert result["disabled"] == 2
    assert not get_user_model().objects.get(username="ad.richards").is_active
    ghost.refresh_from_db()
    assert not ghost.is_active


@override_settings(LDAP={**LDAP_MOCK, "SERVER_URI": "ldap://dc01.nhf.local"})
def test_plain_ldap_is_refused(client):
    with pytest.raises(ldap.DirectoryError, match="plain-text"):
        ldap.authenticate("someone", "x")
    step = ldap.test_connection()[0]
    assert step[1] is False and "plain-text" in step[2]
    resp = client.post("/accounts/login/", {"username": "someone", "password": "x"})
    assert "could not be reached" in resp.content.decode()


def test_directory_disabled_by_default_leaves_local_sign_in_alone(client, agent):
    assert settings.LDAP["ENABLED"] is False
    login(client, agent)


@override_settings(LDAP=LDAP_MOCK)
def test_directory_status_page_tests_connection_without_showing_secrets(client, ict):
    login_verified(client, ict)
    resp = client.get("/security/directory/?test=1&sample=ad.henry")
    body = resp.content.decode()
    assert resp.status_code == 200 and "Service account bind" in body and "NHF-MRS-Supervisors" in body
    assert "service-demo" not in body


def test_directory_status_page_is_closed_to_counter_staff(client, agent):
    login(client, agent)
    assert client.get("/security/directory/").status_code == 403


def test_provision_refuses_unmapped_identity():
    with pytest.raises(NotAuthorised):
        provision(DirectoryIdentity(source="ad", username="x", external_id="1", groups=["Nothing"]))


# --- 3. Entra ID single sign-on --------------------------------------------------
AUTHORITY = "https://login.microsoftonline.com/tenant-id/v2.0"
OIDC_ON = {
    **settings.OIDC,
    "ENABLED": True,
    "AUTHORITY": AUTHORITY,
    "CLIENT_ID": "client-123",
    "CLIENT_SECRET": "secret-xyz",
    "GROUPS_CLAIM": "groups",
    "BUTTON_LABEL": "Sign in with Microsoft",
}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _b64(n):
    return base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


JWKS = {"keys": [{"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256", "n": _b64(KEY.public_key().public_numbers().n), "e": _b64(65537)}]}
DISCOVERY = {
    "issuer": AUTHORITY,
    "authorization_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/tenant-id/discovery/v2.0/keys",
}


def _resp(data, status=200):
    r = mock.Mock(status_code=status)
    r.json.return_value = data
    r.raise_for_status.return_value = None
    return r


def _fake_get(url, timeout):
    return _resp(DISCOVERY if url.endswith("openid-configuration") else JWKS)


def _id_token(nonce, amr=("pwd", "mfa"), groups=("grp-cc",), aud="client-123", key=KEY):
    now = int(time.time())
    claims = {
        "iss": AUTHORITY,
        "aud": aud,
        "iat": now,
        "exp": now + 600,
        "nonce": nonce,
        "oid": "11111111-2222-3333-4444-555555555555",
        "preferred_username": "Tanya.Brown@nhf.gov.jm",
        "given_name": "Tanya",
        "family_name": "Brown",
        "groups": list(groups),
        "amr": list(amr),
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k1"})


def _sso(client, **token_kw):
    cache.clear()
    with mock.patch("apps.directory.oidc.requests.get", side_effect=_fake_get):
        start = client.get("/accounts/oidc/login/")
        assert start.status_code == 302
        q = parse_qs(urlparse(start["Location"]).query)
        assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["client-123"]
        nonce = client.session["oidc"]["nonce"]
        with mock.patch("apps.directory.oidc.requests.post", return_value=_resp({"id_token": _id_token(nonce, **token_kw)})):
            return client.get("/accounts/oidc/callback/", {"code": "abc", "state": q["state"][0]})


@override_settings(OIDC=OIDC_ON, MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_entra_sign_in_with_microsoft_mfa_skips_our_prompt(client, centre):
    GroupMapping.objects.create(source="entra", group="grp-cc", role="customer_care", centre=centre)
    resp = _sso(client)
    assert resp.status_code == 302 and resp["Location"] == "/"
    user = get_user_model().objects.get(username="tanya.brown@nhf.gov.jm")
    assert user.source == "entra" and user.centre == centre
    assert client.session["idp_mfa"] is True
    assert client.get("/").status_code == 200


@override_settings(OIDC=OIDC_ON, MFA_REQUIRED=True, MFA_DEMO_PRIVILEGED_ONLY=False)
def test_entra_sign_in_without_microsoft_mfa_still_needs_ours(client, centre):
    GroupMapping.objects.create(source="entra", group="grp-cc", role="customer_care", centre=centre)
    _sso(client, amr=("pwd",))
    assert client.session["idp_mfa"] is False
    assert "/accounts/mfa/setup/" in client.get("/")["Location"]


@override_settings(OIDC=OIDC_ON)
def test_entra_token_signed_by_another_key_is_refused(client, centre):
    GroupMapping.objects.create(source="entra", group="grp-cc", role="customer_care", centre=centre)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    resp = _sso(client, key=other)
    assert resp["Location"].endswith("/accounts/login/")
    assert not get_user_model().objects.filter(source="entra").exists()
    assert AuditEvent.objects.filter(action="auth.sso_failed").exists()


@override_settings(OIDC=OIDC_ON)
def test_entra_token_for_another_application_is_refused(client, centre):
    GroupMapping.objects.create(source="entra", group="grp-cc", role="customer_care", centre=centre)
    _sso(client, aud="someone-else")
    assert not get_user_model().objects.filter(source="entra").exists()


@override_settings(OIDC=OIDC_ON)
def test_entra_user_in_no_mapped_group_is_refused(client):
    resp = _sso(client, groups=("grp-unknown",))
    assert resp["Location"].endswith("/accounts/login/")
    assert not get_user_model().objects.filter(source="entra").exists()


@override_settings(OIDC=OIDC_ON)
def test_entra_callback_with_wrong_state_is_refused(client):
    with mock.patch("apps.directory.oidc.requests.get", side_effect=_fake_get):
        client.get("/accounts/oidc/login/")
        resp = client.get("/accounts/oidc/callback/", {"code": "abc", "state": "forged"})
    assert resp["Location"].endswith("/accounts/login/")


def test_login_page_shows_microsoft_button_only_when_enabled(client):
    assert "Sign in with Microsoft" not in client.get("/accounts/login/").content.decode()
    assert client.get("/accounts/oidc/login/").status_code == 404
    with override_settings(OIDC=OIDC_ON):
        assert "Sign in with Microsoft" in client.get("/accounts/login/").content.decode()
