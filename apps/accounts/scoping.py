"""Centre scoping: counter staff work their own centre's applications; members are looked up island-wide.

* Island-wide: managers, auditors, the DPO, back-office, application/database administrators, SRN approvers and
  council confirmers, and anyone with no centre on their account.
* Centre-bound (Customer Care, supervisors, print operators): lists, queues and counters show their own centre's
  applications and cards. They can open another centre's application read-only (a member may ask about it at any
  centre) but cannot change it, unless a supervisor has assigned it to them.
* Member records stay searchable island-wide, because a member may be served at any centre; every view is in the
  access log.
"""

from .roles import role_names

ISLAND_WIDE_ROLES = {"manager", "auditor", "dpo", "back_office", "ict_admin", "db_admin", "srn_approver", "mcj_confirmer"}


def sees_all_centres(user):
    return bool(not getattr(user, "centre_id", None) or role_names(user) & ISLAND_WIDE_ROLES)


def scope_by_centre(qs, user, field="centre"):
    """Limit a queryset to the user's centre unless they see all centres; applications assigned to them always show."""
    if sees_all_centres(user):
        return qs
    from django.db.models import Q

    q = Q(**{f"{field}_id": user.centre_id})
    if qs.model.__name__ == "Application":
        q |= Q(assigned_to=user)
    return qs.filter(q)


def can_work_application(user, app):
    return sees_all_centres(user) or app.centre_id == user.centre_id or app.assigned_to_id == user.pk
