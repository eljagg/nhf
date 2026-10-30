"""Microsoft Entra ID single sign-on: OpenID Connect authorization-code flow with PKCE (UM10006).

The ID token is verified against Entra's published signing keys (signature, issuer, audience, expiry, nonce).
If Entra reports that it performed MFA (amr contains "mfa"), our own two-step prompt is skipped for that session.
Group claims must be enabled on the app registration ("groups assigned to the application" keeps the token small).
"""

import base64
import hashlib
import logging
import secrets

import jwt
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from apps.core import audit

from .provisioning import DirectoryIdentity, NotAuthorised, provision

log = logging.getLogger(__name__)
TIMEOUT = 10


class OidcError(Exception):
    """Entra ID sign-in could not be completed."""


def _cfg():
    return settings.OIDC


def discovery():
    """OpenID configuration document, cached for an hour."""
    doc = cache.get("oidc-discovery")
    if doc is None:
        resp = requests.get(f"{_cfg()['AUTHORITY'].rstrip('/')}/.well-known/openid-configuration", timeout=TIMEOUT)
        resp.raise_for_status()
        doc = resp.json()
        cache.set("oidc-discovery", doc, 3600)
    return doc


def _jwks():
    keys = cache.get("oidc-jwks")
    if keys is None:
        resp = requests.get(discovery()["jwks_uri"], timeout=TIMEOUT)
        resp.raise_for_status()
        keys = resp.json()
        cache.set("oidc-jwks", keys, 3600)
    return keys


def verify_id_token(token, nonce):
    """Validate the ID token and return its claims."""
    header = jwt.get_unverified_header(token)
    key_data = next((k for k in _jwks().get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key_data is None:
        cache.delete("oidc-jwks")  # keys rotate: refetch once
        key_data = next((k for k in _jwks().get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key_data is None:
        raise OidcError("Signing key not found")
    claims = jwt.decode(
        token,
        jwt.PyJWK(key_data).key,
        algorithms=["RS256"],
        audience=_cfg()["CLIENT_ID"],
        issuer=discovery()["issuer"],
        options={"require": ["exp", "iat", "aud", "iss", "nonce"]},
    )
    if not secrets.compare_digest(str(claims.get("nonce", "")), str(nonce)):
        raise OidcError("Nonce mismatch")
    return claims


def _pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _redirect_uri(request):
    return request.build_absolute_uri(reverse("oidc:callback"))


def start(request):
    """Send the browser to Entra ID."""
    if not _cfg()["ENABLED"]:
        raise Http404
    verifier, challenge = _pkce()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session["oidc"] = {"state": state, "nonce": nonce, "verifier": verifier, "next": request.GET.get("next", "")}
    params = {
        "client_id": _cfg()["CLIENT_ID"],
        "response_type": "code",
        "redirect_uri": _redirect_uri(request),
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return redirect(requests.Request("GET", discovery()["authorization_endpoint"], params=params).prepare().url)


def identity_from_claims(claims):
    """DirectoryIdentity from Entra ID token claims."""
    upn = str(claims.get("preferred_username") or claims.get("upn") or claims.get("email") or "").lower()
    return DirectoryIdentity(
        source="entra",
        username=upn[:150],
        external_id=str(claims.get("oid") or claims.get("sub")),
        first_name=str(claims.get("given_name", "")),
        last_name=str(claims.get("family_name", "")),
        email=str(claims.get("email") or (upn if "@" in upn else "")),
        groups=[str(g) for g in claims.get(_cfg()["GROUPS_CLAIM"], []) or []],
    )


def callback(request):
    """Entra ID returns here with a code: exchange it, verify the ID token, provision, sign in."""
    if not _cfg()["ENABLED"]:
        raise Http404
    stash = request.session.pop("oidc", None)
    try:
        if not stash or not secrets.compare_digest(request.GET.get("state", ""), stash["state"]):
            raise OidcError("Sign-in state did not match; start again.")
        if request.GET.get("error"):
            raise OidcError(request.GET.get("error_description", request.GET["error"])[:200])
        resp = requests.post(
            discovery()["token_endpoint"],
            data={
                "client_id": _cfg()["CLIENT_ID"],
                "client_secret": _cfg()["CLIENT_SECRET"],
                "grant_type": "authorization_code",
                "code": request.GET.get("code", ""),
                "redirect_uri": _redirect_uri(request),
                "code_verifier": stash["verifier"],
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            raise OidcError(f"Token exchange failed ({resp.status_code})")
        claims = verify_id_token(resp.json()["id_token"], stash["nonce"])
        user = provision(identity_from_claims(claims))
        if user.is_suspended:
            raise NotAuthorised("This account is suspended. Contact your manager or the application administrator.")
    except (OidcError, NotAuthorised, jwt.PyJWTError, requests.RequestException, KeyError) as exc:
        log.warning("Entra ID sign-in failed: %s", exc)
        audit.record("auth.sso_failed", None, f"Entra ID sign-in failed: {str(exc)[:200]}")
        messages.error(request, str(exc) if isinstance(exc, NotAuthorised | OidcError) else "Microsoft sign-in could not be completed. Try again.")
        return redirect("accounts:login")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    amr = claims.get("amr") or []
    request.session["idp_mfa"] = "mfa" in amr
    audit.record("auth.login", user, f"{user.username} signed in with Entra ID{' (Microsoft MFA)' if 'mfa' in amr else ''}", actor=user, sso=True, amr=amr)
    nxt = stash.get("next") or "/"
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
