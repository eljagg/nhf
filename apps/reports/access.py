"""Who may see which reports (RP10001–RP10003, CS10002 need-to-know, Data Protection Act data minimisation).

* Reports, dashboards and the builder: supervisors, managers, back-office, auditors and the DPO.
* Columns that identify a person (names, phone numbers, member numbers): the same roles; centre-bound
  supervisors only for their own centre's records.
* Health columns (medical conditions): only report users who may also see conditions on a record
  (supervisor, manager). Auditors and back-office see counts without conditions.
* The TRN is always masked in reports and exports (last three digits); the full number is on the record.
"""

from apps.accounts.roles import can_view_conditions, has_role
from apps.accounts.scoping import sees_all_centres

REPORT_ROLES = ("supervisor", "manager", "back_office", "auditor", "dpo")
PERSONAL_ROLES = ("supervisor", "manager", "back_office", "auditor", "dpo")
SCHEDULE_ROLES = ("supervisor", "manager", "back_office", "auditor", "dpo")


def can_report(user):
    return has_role(user, *REPORT_ROLES)


def can_see(user, sensitivity):
    """open: anyone with reports · personal: identifies a person · health: medical conditions."""
    if sensitivity == "open":
        return can_report(user)
    if sensitivity == "personal":
        return has_role(user, *PERSONAL_ROLES)
    if sensitivity == "health":
        return can_report(user) and can_view_conditions(user)
    return False


def centre_filter(user):
    """None when the user sees every centre, else their centre id."""
    return None if sees_all_centres(user) else user.centre_id


def mask_trn(value):
    value = str(value or "")
    return f"•••-•••-{value[-3:]}" if len(value) >= 3 else ""
