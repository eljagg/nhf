"""Eligibility and validation rules engine (BR10004–BR10006, programme eligibility).

Rules run on every save of an application and again inside the approval
transaction. Each rule returns findings; an ``error`` finding blocks approval.
Thresholds are parameters the back office can change without code.
"""

from dataclasses import dataclass, field
from datetime import date

from apps.core.models import Parameter

from .models import MedicalCondition, Programme


@dataclass
class Finding:
    """One rule outcome."""

    rule: str
    level: str  # error | warning | info
    message: str
    field: str = ""


@dataclass
class RuleContext:
    """What the rules look at — taken from an application (or a member for sweeps)."""

    dob: date | None
    gender: str
    as_of: date
    has_guardian: bool
    conditions: list = field(default_factory=list)  # MedicalCondition instances
    has_doctor: bool = True
    identity_confirmed: bool = True


@dataclass
class Outcome:
    """Result of an evaluation: findings plus the programmes the member qualifies for."""

    findings: list
    programmes: list

    @property
    def errors(self):
        """Blocking findings."""
        return [f for f in self.findings if f.level == "error"]

    @property
    def ok(self):
        """True when nothing blocks approval."""
        return not self.errors


def age_on(dob, when):
    """Whole years between dob and when."""
    if dob is None:
        return None
    return when.year - dob.year - ((when.month, when.day) < (dob.month, dob.day))


def _within(age, lo, hi):
    return (lo is None or age >= lo) and (hi is None or age <= hi)


def evaluate(ctx: RuleContext) -> Outcome:
    """Run every rule against the context."""
    findings = []
    age = age_on(ctx.dob, ctx.as_of)
    guardian_age = int(Parameter.get("guardian-required-under-age"))
    jadep_age = int(Parameter.get("jadep-age"))

    if not ctx.identity_confirmed:
        findings.append(Finding("IDENTITY", "error", "The applicant's identity has not been confirmed against the TRN service (or an approved SRN).", "trn"))

    # BR10004 guardian mandatory for minors
    if age is not None and age < guardian_age and not ctx.has_guardian:
        findings.append(
            Finding("BR10004", "error", f"Applicant is {age}: a parent or guardian must be recorded for applicants under {guardian_age}.", "guardian_name")
        )

    # BR10006 clinically inconsistent conditions
    for cond in ctx.conditions:
        if cond.sex_restriction and ctx.gender and cond.sex_restriction != ctx.gender:
            sex = "male" if cond.sex_restriction == "M" else "female"
            findings.append(
                Finding("BR10006", "error", f"{cond.name} applies to {sex} patients only; the applicant's TRN record says otherwise.", "conditions")
            )
        if age is not None and not _within(age, cond.min_age, cond.max_age):
            bounds = f"{cond.min_age or 0}–{cond.max_age}" if cond.max_age else f"{cond.min_age}+"
            findings.append(Finding("BR10006", "error", f"{cond.name} is not consistent with age {age} (accepted ages {bounds}).", "conditions"))

    if not ctx.conditions:
        findings.append(Finding("CONDITIONS", "error", "At least one doctor-certified medical condition is required.", "conditions"))
    if not ctx.has_doctor:
        findings.append(Finding("DOCTOR", "error", "The certifying doctor's MCJ registration number is required.", "doctor_mcj"))

    # Programme eligibility
    programmes = []
    cond_ids = {c.pk for c in ctx.conditions}
    for prog in Programme.objects.filter(is_active=True).prefetch_related("conditions"):
        if age is not None and not _within(age, prog.min_age, prog.max_age):
            continue
        if prog.code == "jadep" and age is not None and age < jadep_age:
            continue
        covered = cond_ids & {c.pk for c in prog.conditions.all()}
        if prog.requires_condition and not covered:
            continue
        if prog.auto_assign or covered:
            programmes.append(prog)

    if age is not None and age >= jadep_age and any(p.code == "jadep" for p in programmes):
        findings.append(Finding("BR10005", "info", f"Applicant is {age}: JADEP will be assigned automatically on approval."))
    if ctx.conditions and not programmes:
        findings.append(Finding("PROGRAMME", "warning", "None of the selected conditions is covered by an active programme for this age."))
    return Outcome(findings=findings, programmes=programmes)


def active_conditions():
    """Conditions offered on the form."""
    return MedicalCondition.objects.filter(is_active=True).order_by("name")
