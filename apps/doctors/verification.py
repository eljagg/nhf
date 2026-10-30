"""Check doctors and nurses against their council register, automatically confirming those in good standing."""

from django.utils import timezone

from apps.core import audit
from apps.core.notifications import notify_role

from .registers import COUNCIL_NAMES, RegisterUnavailable, get_adapter


def _confirmed_field(practitioner):
    return "confirmed_with_mcj_at" if practitioner.council == "mcj" else "confirmed_with_ncj_at"


def verify(practitioner, *, user=None):
    """Look the registration number up and record the answer.

    * Pending and in good standing → confirmed automatically ("Council register"), open applications re-checked.
    * Pending but not in good standing / not found → stays pending for a person to decide (never auto-rejected:
      a register copy can be out of date).
    * Already confirmed and the register now shows a problem → flagged and the confirmers notified.

    Returns one of: confirmed, still_pending, ok, concern, unavailable.
    """
    council = practitioner.council
    try:
        result = get_adapter(council).lookup(practitioner.number)
    except RegisterUnavailable as exc:
        audit.record("practitioner.register_unavailable", practitioner, f"{COUNCIL_NAMES[council]} register not checked: {exc}", actor=user)
        return "unavailable"
    before = practitioner.register_status
    practitioner.register_status = result.status if result.found else "not_found"
    if result.found and result.status == "active" and not result.in_good_standing:
        practitioner.register_status = "lapsed"  # active flag but past its expiry date
    practitioner.register_checked_at = timezone.now()
    practitioner.licence_valid_until = result.valid_until
    outcome = "ok"
    if practitioner.status == "pending":
        if result.in_good_standing:
            practitioner.title = result.title or practitioner.title
            practitioner.first_name = result.first_name or practitioner.first_name
            practitioner.last_name = result.last_name or practitioner.last_name
            if result.specialty and practitioner.council == "mcj" and not practitioner.specialty:
                practitioner.specialty = result.specialty
            practitioner.status = "confirmed"
            practitioner.verified_via = "register"
            setattr(practitioner, _confirmed_field(practitioner), timezone.now())
            practitioner.decision_note = f"Verified against the {COUNCIL_NAMES[council]} register"
            outcome = "confirmed"
        else:
            outcome = "still_pending"
    elif practitioner.register_concern:
        outcome = "concern"
    practitioner.save()
    summary = f"{practitioner} checked against the {COUNCIL_NAMES[council]} register: {practitioner.get_register_status_display()}"
    audit.record("practitioner.register_checked", practitioner, summary, actor=user, status=practitioner.register_status, outcome=outcome)
    if outcome == "confirmed":
        audit.record("practitioner.auto_confirmed", practitioner, f"{practitioner} confirmed automatically from the council register", actor=user)
        if council == "mcj":
            from apps.members.models import Application
            from apps.members.services import refresh_status

            for app in Application.objects.filter(doctor=practitioner, status__in=Application.OPEN_STATUSES):
                refresh_status(app)
    if outcome == "concern" and before != practitioner.register_status:
        notify_role(
            "mcj_confirmer",
            "practitioner-register-changed",
            obj=practitioner,
            link=practitioner_link(practitioner),
            who=str(practitioner),
            status=practitioner.get_register_status_display(),
        )
    return outcome


def practitioner_link(practitioner):
    """Profile URL."""
    return f"/doctors/{practitioner.mcj_number}/" if practitioner.council == "mcj" else f"/doctors/nurses/{practitioner.ncj_number}/"
