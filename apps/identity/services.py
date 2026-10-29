"""Identity Verification module: TRN validation, match, SRN issue, identity writes."""

import contextlib
import re
import secrets
import time
import unicodedata

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.core import audit
from apps.core.models import Parameter

from .adapters import ServiceUnavailable, get_adapter
from .models import SrnIssue, TajIdentity, TrnValidation

TRN_RE = re.compile(r"^\d{9}$")


def clean_trn(value):
    """Digits only; TRNs are nine digits."""
    return re.sub(r"\D", "", value or "")


def is_valid_format(trn):
    """True for nine digits."""
    return bool(TRN_RE.match(trn or ""))


def _norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", value.lower())


def compare(form_identity, payload):
    """Field-by-field comparison of the paper form with the TAJ identity (TV10003). Returns a list of differences."""
    diffs = []
    if not form_identity or not payload:
        return diffs
    for key, label in [("first_name", "First name"), ("last_name", "Last name"), ("middle_name", "Middle name")]:
        form_val = form_identity.get(key, "")
        if key == "middle_name" and not form_val:
            continue
        if _norm(form_val) != _norm(payload.get(key, "")):
            diffs.append({"field": key, "label": label, "form": form_val, "taj": payload.get(key, "")})
    if form_identity.get("dob") and str(form_identity["dob"]) != str(payload.get("dob")):
        diffs.append({"field": "dob", "label": "Date of birth", "form": str(form_identity["dob"]), "taj": payload.get("dob")})
    if form_identity.get("gender") and form_identity["gender"] != payload.get("gender"):
        diffs.append({"field": "gender", "label": "Gender", "form": form_identity["gender"], "taj": payload.get("gender")})
    return diffs


def start_validation(trn, *, user=None, purpose="application", form_identity=None):
    """Record a validation and hand it to the identity worker. The counter polls for the result."""
    from .tasks import run_trn_validation

    validation = TrnValidation.objects.create(trn=trn, requested_by=user, purpose=purpose, form_identity=form_identity or None)
    audit.record("trn.requested", validation, f"TRN {trn} sent for validation ({purpose})", actor=user)
    transaction.on_commit(lambda: run_trn_validation.delay(validation.pk))
    return validation


def perform_validation(validation_id):
    """Call the adapter and store the outcome. Runs in the worker (or inline without Redis)."""
    validation = TrnValidation.objects.get(pk=validation_id)
    if validation.is_done:
        return validation
    adapter = get_adapter()
    started = time.monotonic()
    try:
        result = adapter.lookup(validation.trn)
    except ServiceUnavailable as exc:
        validation.status = "unavailable"
        validation.message = str(exc)[:300]
    else:
        if result.found:
            validation.status = "valid"
            validation.payload = result.identity
            if validation.purpose == "screen":
                validation.match_result = "screen"
            elif validation.form_identity:
                validation.differences = compare(validation.form_identity, result.identity)
                validation.match_result = "mismatch" if validation.differences else "match"
        else:
            validation.status = "invalid"
            validation.message = "The Tax Office has no record of this TRN."
    validation.adapter = adapter.name
    validation.duration_ms = int((time.monotonic() - started) * 1000)
    validation.completed_at = timezone.now()
    validation.save()
    audit.record(
        "trn.completed",
        validation,
        f"TRN {validation.trn}: {validation.get_status_display()}{' — ' + validation.get_match_result_display() if validation.match_result else ''}",
        actor=validation.requested_by,
    )
    from apps.members.services import on_validation_complete

    on_validation_complete(validation)
    return validation


@contextlib.contextmanager
def identity_write():
    """Allow writes to protected identity fields (name, DOB, gender) for this transaction only.

    Sets a transaction-local PostgreSQL setting that the members_member trigger checks (BR10001–BR10003).
    """
    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT set_config('nhf.identity_write', 'on', true)")
        try:
            yield
        finally:
            with connection.cursor() as cur:
                cur.execute("SELECT set_config('nhf.identity_write', 'off', true)")


# ---------------------------------------------------------------------------
# Special Registration Numbers
# ---------------------------------------------------------------------------
def duplicate_check(first_name, last_name, dob):
    """SR10004: look for the same person among members, the TRN register and open SRN requests."""
    from apps.members.models import Member

    members = list(Member.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, dob=dob).values("member_number", "trn", "is_srn")[:5])
    taj = list(TajIdentity.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, dob=dob).values_list("trn", flat=True)[:5])
    open_requests = list(
        SrnIssue.objects.filter(first_name__iexact=first_name, last_name__iexact=last_name, dob=dob, status="requested").values_list("pk", flat=True)[:5]
    )
    return {"members": members, "trn_register": taj, "open_requests": open_requests, "clear": not (members or taj), "checked_at": timezone.now().isoformat()}


def generate_srn():
    """SR10002–SR10003: prefix digit then eight random digits, unique across SRNs, members and the TRN register."""
    from apps.members.models import Member

    prefix = str(Parameter.get("srn-prefix"))
    for _ in range(50):
        candidate = prefix + "".join(secrets.choice("0123456789") for _ in range(9 - len(prefix)))
        if (
            SrnIssue.objects.filter(srn=candidate).exists()
            or Member.objects.filter(trn=candidate).exists()
            or TajIdentity.objects.filter(trn=candidate).exists()
        ):
            continue
        return candidate
    raise RuntimeError("Could not generate a unique SRN")


def request_srn(*, user, first_name, middle_name, last_name, dob, gender, reason):
    """SR10001: a staff request that needs management approval."""
    from apps.core.notifications import notify_role

    issue = SrnIssue.objects.create(
        requested_by=user,
        first_name=first_name,
        middle_name=middle_name,
        last_name=last_name,
        dob=dob,
        gender=gender,
        reason=reason,
        duplicate_check=duplicate_check(first_name, last_name, dob),
    )
    audit.record("srn.requested", issue, f"SRN requested for {issue.full_name}", actor=user)
    notify_role(
        "srn_approver",
        "srn-approval-needed",
        obj=issue,
        link=f"/identity/srn/{issue.pk}/",
        requester=user.display_name() if user else "System",
        name=issue.full_name,
        dob=dob,
        reason=reason,
    )
    notify_role(
        "manager",
        "srn-approval-needed",
        obj=issue,
        link=f"/identity/srn/{issue.pk}/",
        requester=user.display_name() if user else "System",
        name=issue.full_name,
        dob=dob,
        reason=reason,
    )
    return issue


def approve_srn(issue, *, user, note=""):
    """Manager approval: the duplicate check is re-run, then a unique SRN is issued."""
    if issue.requested_by_id == user.pk:
        raise PermissionError("The person who requested an SRN cannot approve it.")
    issue.duplicate_check = duplicate_check(issue.first_name, issue.last_name, issue.dob)
    for _ in range(5):
        try:
            with transaction.atomic():
                issue.srn = generate_srn()
                issue.status = "approved"
                issue.decided_by = user
                issue.decided_at = timezone.now()
                issue.decision_note = note
                issue.save()
            break
        except IntegrityError:
            continue
    audit.record("srn.approved", issue, f"SRN {issue.srn} issued for {issue.full_name}", actor=user)
    from apps.members.services import on_srn_decided

    on_srn_decided(issue)
    return issue


def decline_srn(issue, *, user, note):
    """Manager declines the request."""
    issue.status = "declined"
    issue.decided_by = user
    issue.decided_at = timezone.now()
    issue.decision_note = note
    issue.save()
    audit.record("srn.declined", issue, f"SRN declined for {issue.full_name}: {note}", actor=user)
    from apps.members.services import on_srn_decided

    on_srn_decided(issue)
    return issue
