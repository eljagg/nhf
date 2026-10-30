"""Template context: product identity and the role-aware module navigation."""

from django.conf import settings
from django.urls import reverse

from apps.accounts.roles import has_role


def _item(label, url_name, request, roles=None, count=None, note=""):
    user = request.user
    if roles and not has_role(user, *roles):
        return None
    if url_name is None:
        return {"label": label, "url": None, "note": note}
    url = reverse(url_name)
    return {"label": label, "url": url, "active": request.path.startswith(url) and url != "/" or request.path == url, "count": count}


def site(request):
    """Product names, version, unread count and navigation."""
    ctx = {
        "PRODUCT_NAME": settings.PRODUCT_NAME,
        "BUILT_BY": settings.BUILT_BY,
        "EDITION_NAME": settings.EDITION_NAME,
        "CLIENT_NAME": settings.CLIENT_NAME,
        "VERSION": settings.VERSION,
        "DEMO_MODE": getattr(settings, "DEMO_MODE", True),
    }
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ctx
    from apps.doctors.models import Doctor
    from apps.identity.models import SrnIssue
    from apps.members.models import Application

    from .models import Notification

    ctx["UNREAD"] = Notification.objects.filter(recipient_user=user, channel="inapp", read_at__isnull=True).count()
    proc = ("customer_care", "supervisor", "manager")
    online = Application.objects.filter(channel="online", status__in=Application.OPEN_STATUSES).count() if has_role(user, *proc) else None
    srn = SrnIssue.objects.filter(status="requested").count() if has_role(user, "manager", "srn_approver") else None
    mcj = Doctor.objects.filter(status="pending").count() if has_role(user, "manager", "mcj_confirmer") else None
    alerts_open = dsr_open = breach_open = None
    if has_role(user, "ict_admin", "manager", "auditor"):
        from apps.security.models import SecurityAlert

        alerts_open = SecurityAlert.objects.filter(acknowledged_at__isnull=True).count()
    if has_role(user, "dpo", "manager", "auditor"):
        from apps.privacy.models import Breach, DataSubjectRequest

        dsr_open = DataSubjectRequest.objects.filter(status__in=("open", "in_progress")).count()
        breach_open = Breach.objects.filter(reported_to_commissioner_at__isnull=True).exclude(status="closed").count()
    sections = [
        (
            "Members",
            [
                _item("Home", "core:home", request),
                _item("Applications", "members:applications", request, ("customer_care", "supervisor", "manager", "auditor")),
                _item("Tracking search", "members:search", request, ("customer_care", "supervisor", "manager", "auditor")),
                _item("Online Intake", "intake:queue", request, proc, online),
            ],
        ),
        (
            "Identity Verification",
            [
                _item("TRN / SRN screening", "identity:screen", request, proc),
                _item("SRN approvals", "identity:srn-list", request, ("customer_care", "supervisor", "manager", "srn_approver"), srn),
            ],
        ),
        (
            "Doctors",
            [
                _item("NHF Doctors register", "doctors:list", request, ("customer_care", "supervisor", "manager", "mcj_confirmer")),
                _item("MCJ confirmations", "doctors:confirmations", request, ("manager", "mcj_confirmer", "supervisor"), mcj),
            ],
        ),
        (
            "Card Services",
            [
                _item("Print queue", "cards:queue", request, ("customer_care", "supervisor", "manager", "print_operator")),
                _item("Verify and dispatch", None, request, note="A2"),
            ],
        ),
        (
            "Insights",
            [
                _item("Dashboards and reports", None, request, note="A3"),
                _item("Documents and scanning", None, request, note="A3"),
            ],
        ),
        (
            "Data protection",
            [
                _item("Privacy dashboard", "privacy:dashboard", request, ("dpo", "manager", "auditor"), dsr_open),
                _item("Requests from members", "privacy:dsr-list", request, ("dpo", "manager", "auditor")),
                _item("Breach register", "privacy:breach-list", request, ("dpo", "manager", "auditor"), breach_open),
                _item("Processing register", "privacy:register", request, ("dpo", "manager", "auditor")),
            ],
        ),
        (
            "Registry Core",
            [
                _item("Security", "security:dashboard", request, ("ict_admin", "manager", "auditor"), alerts_open),
                _item("User activity", "security:activity", request, ("ict_admin", "manager", "auditor")),
                _item("Audit trail", "core:audit", request, ("auditor", "manager", "ict_admin")),
                _item("Integration Hub log", "core:integrations", request, ("ict_admin", "manager", "auditor")),
                _item("Temporary roles", "accounts:temporary-roles", request, ("manager", "ict_admin")),
                _item("Back office (configuration)", "admin:index", request, ("back_office", "ict_admin", "auditor", "dpo")),
                _item("API documentation", "api-docs", request, ("ict_admin", "manager")),
            ],
        ),
    ]
    ctx["NAV"] = [{"title": t, "items": [i for i in items if i]} for t, items in sections if any(items)]
    return ctx
