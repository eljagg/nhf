"""Role catalogue: global, process-specific and temporary roles (UM10007, TOR §4 admin separation)."""

from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

ROLES = {
    # global roles
    "customer_care": ("Customer Care", "Counter and back-office processing of applications and change forms."),
    "supervisor": ("Supervisor", "Assigns online applications, oversees a centre's queues."),
    "manager": ("Manager", "Approves Special Registration Numbers and exceptions; sees all centres."),
    "back_office": ("Back-office power user", "Configures programmes, benefits, medical conditions and reference data."),
    "ict_admin": ("Application administrator", "Manages user accounts and roles. No access to member records."),
    "db_admin": ("Database administrator", "Database operations only; kept separate from application administration."),
    "dpo": ("Data Protection Officer", "Data-subject requests, breach register, processing register, retention (Data Protection Act 2020)."),
    "auditor": ("Auditor", "Read-only access to records and the audit trail; medical conditions masked."),
    # process-specific roles
    "srn_approver": ("SRN approver", "May approve Special Registration Numbers."),
    "mcj_confirmer": (
        "Council confirmer (MCJ / NCJ)",
        "Confirms doctors with the Medical Council and nurses with the Nursing Council when the register check cannot.",
    ),
    "print_operator": ("Card print operator", "Works the card print queue."),
}

# Roles allowed to see medical conditions in full (CS10002 need-to-know).
CLINICAL_VIEW_ROLES = {"customer_care", "supervisor", "manager"}


def role_names(user):
    """Set of role codes the user holds now, including active temporary grants."""
    if not user or not user.is_authenticated:
        return set()
    cached = getattr(user, "_role_cache", None)
    if cached is not None:
        return cached
    names = set(user.groups.values_list("name", flat=True))
    now = timezone.now()
    names |= set(user.temporary_roles.filter(revoked_at__isnull=True, starts_at__lte=now, expires_at__gt=now).values_list("group__name", flat=True))
    if user.is_superuser:
        names |= set(ROLES)
    user._role_cache = names
    return names


def has_role(user, *roles):
    """True if the user holds any of the roles."""
    return bool(role_names(user) & set(roles))


def can_view_conditions(user):
    """Need-to-know check for medical conditions."""
    return has_role(user, *CLINICAL_VIEW_ROLES)


def users_with_role(role):
    """Active users holding the role permanently or temporarily."""
    now = timezone.now()
    user_model = get_user_model()
    return (
        user_model.objects.filter(is_active=True)
        .filter(
            Q(groups__name=role)
            | Q(
                temporary_roles__group__name=role,
                temporary_roles__revoked_at__isnull=True,
                temporary_roles__starts_at__lte=now,
                temporary_roles__expires_at__gt=now,
            )
        )
        .distinct()
    )


def role_required(*roles):
    """View decorator: 403 unless the user holds one of the roles."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


# Everyone who works member records.
MEMBER_ROLES = ("customer_care", "supervisor", "manager", "auditor")
PROCESS_ROLES = ("customer_care", "supervisor", "manager")
