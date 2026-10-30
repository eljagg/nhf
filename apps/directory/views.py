"""Directory status page for application administrators."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import render

from apps.accounts.roles import role_required
from apps.core import audit

from .models import GroupMapping


@role_required("ict_admin", "manager", "auditor")
def status(request):
    """Configuration (no secrets), test connection, group mappings, directory accounts."""
    from . import ldap

    steps = None
    sample = request.GET.get("sample", "").strip()
    if request.GET.get("test") and settings.LDAP["ENABLED"]:
        steps = ldap.test_connection(sample)
        audit.record(
            "directory.tested", None, f"Directory connection tested{' with ' + sample if sample else ''}: {'ok' if all(s[1] for s in steps) else 'failed'}"
        )
    user_model = get_user_model()
    ctx = {
        "ldap": {k: v for k, v in settings.LDAP.items() if k != "BIND_PASSWORD"},
        "ldap_mock": ldap.is_mock(),
        "oidc": {k: v for k, v in settings.OIDC.items() if k != "CLIENT_SECRET"},
        "oidc_secret_set": bool(settings.OIDC["CLIENT_SECRET"]),
        "bind_password_set": bool(settings.LDAP["BIND_PASSWORD"]),
        "steps": steps,
        "sample": sample,
        "mappings": GroupMapping.objects.select_related("centre"),
        "dir_users": user_model.objects.exclude(source="local").order_by("source", "username")[:200],
        "local_admins": user_model.objects.filter(source="local", is_active=True, groups__name="ict_admin").distinct(),
        "page_title": "Directory sign-in",
    }
    return render(request, "directory/status.html", ctx)
