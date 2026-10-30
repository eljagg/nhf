"""Active Directory over LDAPS (ldap3, pure Python). "mock://demo" gives a built-in demonstration directory.

Flow: bind with the service account → find the user by sAMAccountName → refuse disabled accounts → bind as the user with the
password typed (that is the password check; the password is never stored) → read groups (nested, via the AD in-chain rule).
"""

import logging
import ssl
import uuid

from django.conf import settings
from ldap3 import ALL_ATTRIBUTES, MOCK_SYNC, SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from .provisioning import DirectoryIdentity

log = logging.getLogger(__name__)

USER_ATTRS = ["sAMAccountName", "givenName", "sn", "mail", "memberOf", "userAccountControl", "objectGUID", "distinguishedName"]
ACCOUNTDISABLE = 0x0002
IN_CHAIN = "1.2.840.113556.1.4.1941"  # LDAP_MATCHING_RULE_IN_CHAIN: nested group membership in AD

DEMO_BASE = "DC=demo,DC=nhf,DC=local"
DEMO_USERS = [
    # sAMAccountName, given, sn, groups
    ("ad.campbell", "Shelly-Ann", "Campbell", ["NHF-MRS-CustomerCare", "NHF-Centre-HWT"]),
    ("ad.richards", "Romain", "Richards", ["NHF-MRS-CustomerCare", "NHF-Centre-MBJ"]),
    ("ad.henry", "Yvette", "Henry", ["NHF-MRS-Supervisors", "NHF-MRS-CustomerCare", "NHF-Centre-HWT"]),
    ("ad.auditor", "Courtney", "Walsh", ["NHF-MRS-Auditors"]),
    ("ad.nogroup", "Pat", "Outsider", ["NHF-Finance"]),
    ("ad.disabled", "Dee", "Activated", ["NHF-MRS-CustomerCare"]),
]


class DirectoryError(Exception):
    """The directory could not be reached or answered unexpectedly."""


def _cfg():
    return settings.LDAP


def is_mock():
    """Built-in demonstration directory in use."""
    return _cfg()["SERVER_URI"].startswith("mock://")


_MOCK_SERVER = None


def _demo_password():
    import os

    return os.environ.get("DEMO_PASSWORD", "NhfDemo-2026!")


def _mock_connection(user=None, password=None):
    """In-memory directory with a service account and a few staff in mapped and unmapped groups."""
    global _MOCK_SERVER
    if _MOCK_SERVER is None:
        _MOCK_SERVER = Server("demo-directory")
    conn = Connection(_MOCK_SERVER, user=user, password=password, client_strategy=MOCK_SYNC, raise_exceptions=False)
    seed = Connection(_MOCK_SERVER, client_strategy=MOCK_SYNC)
    if not getattr(_MOCK_SERVER, "_nhf_seeded", False):
        seed.strategy.add_entry(f"CN=svc-mrs,OU=Service,{DEMO_BASE}", {"objectClass": ["user"], "sAMAccountName": "svc-mrs", "userPassword": "service-demo"})
        for sam, given, sn, groups in DEMO_USERS:
            seed.strategy.add_entry(
                f"CN={given} {sn},OU=Staff,{DEMO_BASE}",
                {
                    "objectClass": ["user"],
                    "sAMAccountName": sam,
                    "givenName": given,
                    "sn": sn,
                    "mail": f"{sam}@demo.nhf.local",
                    "memberOf": [f"CN={g},OU=Groups,{DEMO_BASE}" for g in groups],
                    "userAccountControl": 514 if sam == "ad.disabled" else 512,
                    "objectGUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, sam)),
                    "userPassword": _demo_password(),
                },
            )
        _MOCK_SERVER._nhf_seeded = True
    return conn


def _server():
    cfg = _cfg()
    uri = cfg["SERVER_URI"]
    if uri.startswith("ldap://") and not cfg["ALLOW_PLAIN"]:
        raise DirectoryError("Refusing a plain-text LDAP connection. Use ldaps:// (or set LDAP_ALLOW_PLAIN=1 for a lab only).")
    tls = None
    if uri.startswith("ldaps://"):
        tls = Tls(validate=ssl.CERT_REQUIRED, ca_certs_file=cfg["CA_CERT_FILE"] or None, version=ssl.PROTOCOL_TLS_CLIENT)
    return Server(uri, use_ssl=uri.startswith("ldaps://"), tls=tls, connect_timeout=cfg["TIMEOUT"])


def _connect(user, password):
    if is_mock():
        conn = _mock_connection(user, password)
    else:
        conn = Connection(_server(), user=user, password=password, receive_timeout=_cfg()["TIMEOUT"], raise_exceptions=False, auto_referrals=False)
    try:
        ok = conn.bind()
    except LDAPException as exc:
        raise DirectoryError(f"Directory unreachable: {exc}") from exc
    return conn if ok else None


def _service_connection():
    cfg = _cfg()
    bind_dn = cfg["BIND_DN"] or (f"CN=svc-mrs,OU=Service,{DEMO_BASE}" if is_mock() else "")
    bind_pw = cfg["BIND_PASSWORD"] or ("service-demo" if is_mock() else "")
    conn = _connect(bind_dn, bind_pw)
    if conn is None:
        raise DirectoryError("The service account could not bind to the directory (check LDAP_BIND_DN / LDAP_BIND_PASSWORD).")
    return conn


def _search_base():
    return _cfg()["USER_SEARCH_BASE"] or (DEMO_BASE if is_mock() else "")


def _first(entry, attr):
    value = entry.get(attr)
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _cn(dn):
    first = str(dn).split(",", 1)[0]
    return first.split("=", 1)[1] if "=" in first else first


def find_user(username, conn=None):
    """Look a user up by sAMAccountName; returns (dn, attributes) or None."""
    conn = conn or _service_connection()
    flt = _cfg()["USER_FILTER"].format(username=escape_filter_chars(username))
    if is_mock():
        flt = f"(sAMAccountName={escape_filter_chars(username)})"
    conn.search(_search_base(), flt, search_scope=SUBTREE, attributes=ALL_ATTRIBUTES if is_mock() else USER_ATTRS, size_limit=2)
    if len(conn.entries) != 1:
        return None
    entry = conn.response[0]
    return entry["dn"], entry["attributes"]


def _groups(conn, dn, attrs):
    if _cfg()["NESTED_GROUPS"] and not is_mock():
        base = _cfg()["GROUP_SEARCH_BASE"] or _search_base()
        conn.search(base, f"(member:{IN_CHAIN}:={escape_filter_chars(dn)})", search_scope=SUBTREE, attributes=["cn"])
        return sorted({_first(e["attributes"], "cn") for e in conn.response if e.get("type") == "searchResEntry"})
    member_of = attrs.get("memberOf") or []
    return sorted({_cn(g) for g in (member_of if isinstance(member_of, list) else [member_of])})


def identity_from(dn, attrs, groups):
    """DirectoryIdentity from LDAP attributes."""
    uac = int(_first(attrs, "userAccountControl") or 512)
    return DirectoryIdentity(
        source="ad",
        username=str(_first(attrs, "sAMAccountName")).lower(),
        external_id=str(_first(attrs, "objectGUID")),
        first_name=str(_first(attrs, "givenName")),
        last_name=str(_first(attrs, "sn")),
        email=str(_first(attrs, "mail")),
        groups=groups,
        enabled=not (uac & ACCOUNTDISABLE),
    )


def authenticate(username, password):
    """Check a username and password against the directory. Returns a DirectoryIdentity, or None for a wrong password / unknown user."""
    if not username or not password:
        return None
    service = _service_connection()
    found = find_user(username, service)
    if found is None:
        return None
    dn, attrs = found
    groups = _groups(service, dn, attrs)
    identity = identity_from(dn, attrs, groups)
    if not identity.enabled:
        return identity  # provisioning refuses and deactivates
    user_conn = _connect(dn, password)
    if user_conn is None:
        return None
    user_conn.unbind()
    return identity


def lookup(username):
    """Current directory state of a user, without a password (nightly sync)."""
    service = _service_connection()
    found = find_user(username, service)
    if found is None:
        return None
    dn, attrs = found
    return identity_from(dn, attrs, _groups(service, dn, attrs))


def test_connection(sample_username=""):
    """Service bind, then optionally look one user up. Returns a list of (step, ok, detail) for the status page."""
    steps = []
    try:
        conn = _service_connection()
        steps.append(("Service account bind", True, "demonstration directory" if is_mock() else _cfg()["SERVER_URI"]))
    except DirectoryError as exc:
        return [("Service account bind", False, str(exc))]
    if sample_username:
        found = find_user(sample_username, conn)
        if found:
            dn, attrs = found
            ident = identity_from(dn, attrs, _groups(conn, dn, attrs))
            steps.append(("User lookup", True, f"{dn} · groups: {', '.join(ident.groups) or 'none'} · {'enabled' if ident.enabled else 'DISABLED'}"))
        else:
            steps.append(("User lookup", False, f"No single user found for '{sample_username}'"))
    return steps
