"""Datasets for the report builder (RP10003): what can be listed, filtered, grouped and counted, with no IT involvement.

Every field is declared here with its label, how it is read from the database, its type and how sensitive it is.
Nothing outside these declarations can be selected, filtered or grouped, so a saved report can never reach a column
the platform has not deliberately offered (and checked against the user's role) — the builder never runs free SQL.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db.models import Avg, Case, CharField, Count, DurationField, ExpressionWrapper, F, Value, When
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from .access import can_see, centre_filter, mask_trn

OPS = {
    "eq": "is",
    "ne": "is not",
    "contains": "contains",
    "gte": "on or after / at least",
    "lte": "on or before / at most",
    "yes": "is yes",
    "no": "is no",
}
OPS_BY_TYPE = {
    "text": ("eq", "ne", "contains"),
    "choice": ("eq", "ne"),
    "date": ("gte", "lte", "eq"),
    "number": ("gte", "lte", "eq"),
    "bool": ("yes", "no"),
    "duration": ("gte", "lte"),
}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    lookup: str  # ORM path or the name of an annotation in Dataset.annotate()
    type: str = "text"  # text | choice | date | number | bool | duration
    sensitivity: str = "open"  # open | personal | health
    choices: tuple = ()
    groupable: bool = True
    filterable: bool = True
    mask: str = ""  # "trn" → shown as •••-•••-123


@dataclass
class Dataset:
    key: str
    label: str
    description: str
    model_path: str
    centre_field: str  # used to limit centre-bound supervisors to their own centre
    fields: list = field(default_factory=list)

    def field_map(self):
        return {f.key: f for f in self.fields}

    def model(self):
        from django.apps import apps

        return apps.get_model(self.model_path)

    def visible_fields(self, user):
        return [f for f in self.fields if can_see(user, f.sensitivity)]

    def base(self, user):
        qs = self.model().objects.all()
        qs = annotate(self.key, qs)
        centre = centre_filter(user)
        if centre is not None:
            qs = qs.filter(**{f"{self.centre_field}_id": centre})
        return qs


def _age_band(prefix=""):
    """Age band from date of birth, relative to today (the bands NHF uses: children under 19, JADEP at 60)."""
    today = timezone.localdate()

    def years_ago(n):
        try:
            return today.replace(year=today.year - n)
        except ValueError:  # 29 February
            return today.replace(year=today.year - n, day=28)

    dob = f"{prefix}dob"
    return Case(
        When(**{f"{dob}__isnull": True}, then=Value("Unknown")),
        When(**{f"{dob}__gt": years_ago(19)}, then=Value("0–18")),
        When(**{f"{dob}__gt": years_ago(40)}, then=Value("19–39")),
        When(**{f"{dob}__gt": years_ago(60)}, then=Value("40–59")),
        default=Value("60+"),
        output_field=CharField(),
    )


def annotate(key, qs):
    """Computed columns a dataset offers (dates without time, months, age band, turnaround)."""
    if key == "applications":
        return qs.annotate(
            received_day=TruncDate("received_at", tzinfo=timezone.get_current_timezone()),
            received_month=TruncMonth("received_at", tzinfo=timezone.get_current_timezone()),
            decided_day=TruncDate("decided_at", tzinfo=timezone.get_current_timezone()),
            turnaround=ExpressionWrapper(F("decided_at") - F("received_at"), output_field=DurationField()),
            age_band=_age_band(),
        )
    if key == "members":
        return qs.annotate(
            registered_day=TruncDate("registered_at", tzinfo=timezone.get_current_timezone()),
            registered_month=TruncMonth("registered_at", tzinfo=timezone.get_current_timezone()),
            age_band=_age_band(),
        )
    if key == "cards":
        return qs.annotate(
            queued_day=TruncDate("queued_at", tzinfo=timezone.get_current_timezone()),
            printed_day=TruncDate("printed_at", tzinfo=timezone.get_current_timezone()),
            dispatched_day=TruncDate("dispatched_at", tzinfo=timezone.get_current_timezone()),
            queue_wait=ExpressionWrapper(F("printed_at") - F("queued_at"), output_field=DurationField()),
        )
    if key == "interactions":
        return qs.annotate(
            day=TruncDate("at", tzinfo=timezone.get_current_timezone()),
            month=TruncMonth("at", tzinfo=timezone.get_current_timezone()),
        )
    return qs


def _choices(model_path, attr):
    from django.apps import apps

    model, name = model_path.rsplit(".", 1)
    return tuple(getattr(apps.get_model(model, name), attr))


def _build():
    from apps.cards.models import Card
    from apps.core.models import PARISHES
    from apps.interactions.models import Interaction
    from apps.members.models import GENDERS, Application, Member

    return {
        "applications": Dataset(
            "applications",
            "Applications",
            "Every application and change form, with channel, status, centre and how long it took.",
            "members.Application",
            "centre",
            [
                Field("tracking_number", "Tracking no.", "tracking_number", groupable=False),
                Field("kind", "Kind", "kind", "choice", choices=tuple(Application.KINDS)),
                Field("channel", "Channel", "channel", "choice", choices=tuple(Application.CHANNELS)),
                Field("status", "Status", "status", "choice", choices=tuple(Application.STATUSES)),
                Field("centre", "Centre", "centre__name"),
                Field("received_day", "Received (date)", "received_day", "date"),
                Field("received_month", "Received (month)", "received_month", "date", filterable=False),
                Field("decided_day", "Decided (date)", "decided_day", "date"),
                Field("turnaround", "Turnaround (received to decision)", "turnaround", "duration", groupable=False),
                Field("rejection_reason", "Rejection reason", "rejection_reason__label"),
                Field("parish", "Parish", "parish", "choice", choices=tuple(PARISHES)),
                Field("gender", "Gender", "gender", "choice", choices=tuple(GENDERS)),
                Field("age_band", "Age band", "age_band", "choice", choices=tuple((b, b) for b in ("0–18", "19–39", "40–59", "60+", "Unknown"))),
                Field("screening_only", "Screening only", "screening_only", "bool"),
                Field("plwd", "Disability (JCPD)", "plwd", "bool"),
                Field("entered_by", "Entered by", "entered_by__username"),
                Field("decided_by", "Decided by", "decided_by__username"),
                Field("doctor_mcj", "Doctor MCJ no.", "doctor_mcj"),
                Field("applicant", "Applicant surname", "last_name", sensitivity="personal", groupable=False),
                Field("trn", "TRN (masked)", "trn", sensitivity="personal", groupable=False, filterable=False, mask="trn"),
            ],
        ),
        "members": Dataset(
            "members",
            "Members",
            "Registered members with where and when they registered, programmes and (for clinical roles) conditions.",
            "members.Member",
            "registered_centre",
            [
                Field("member_number", "Member no.", "member_number", sensitivity="personal", groupable=False),
                Field("status", "Status", "status", "choice", choices=tuple(Member.STATUSES)),
                Field("registered_centre", "Registered at", "registered_centre__name"),
                Field("collection_centre", "Collection centre", "collection_centre__name"),
                Field("registered_day", "Registered (date)", "registered_day", "date"),
                Field("registered_month", "Registered (month)", "registered_month", "date", filterable=False),
                Field("parish", "Parish", "parish", "choice", choices=tuple(PARISHES)),
                Field("gender", "Gender", "gender", "choice", choices=tuple(GENDERS)),
                Field("age_band", "Age band", "age_band", "choice", choices=tuple((b, b) for b in ("0–18", "19–39", "40–59", "60+", "Unknown"))),
                Field("programme", "Programme", "enrolments__programme__name"),
                Field("plwd", "Disability (JCPD)", "plwd", "bool"),
                Field("is_srn", "Has an SRN (no TRN)", "is_srn", "bool"),
                Field("condition", "Medical condition", "conditions__condition__name", sensitivity="health"),
                Field(
                    "severity",
                    "Condition severity",
                    "conditions__severity",
                    "choice",
                    sensitivity="health",
                    choices=(("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe")),
                ),
                Field("surname", "Surname", "last_name", sensitivity="personal", groupable=False),
                Field("trn", "TRN (masked)", "trn", sensitivity="personal", groupable=False, filterable=False, mask="trn"),
            ],
        ),
        "cards": Dataset(
            "cards",
            "Cards",
            "Every card produced: why, where, and how long it waited to print.",
            "cards.Card",
            "centre",
            [
                Field("state", "State", "state", "choice", choices=tuple(Card.STATES)),
                Field("reason", "Reason", "reason", "choice", choices=tuple(Card.REASONS)),
                Field("centre", "Centre", "centre__name"),
                Field("version_no", "Card version", "version_no", "number"),
                Field("queued_day", "Queued (date)", "queued_day", "date"),
                Field("printed_day", "Printed (date)", "printed_day", "date"),
                Field("dispatched_day", "Dispatched (date)", "dispatched_day", "date"),
                Field("queue_wait", "Queue to print", "queue_wait", "duration", groupable=False),
                Field("member_number", "Member no.", "member__member_number", sensitivity="personal", groupable=False),
            ],
        ),
        "interactions": Dataset(
            "interactions",
            "Interactions",
            "The interaction log: visits, calls, e-mails, SMS and system events with members.",
            "interactions.Interaction",
            "centre",
            [
                Field("kind", "Kind", "kind", "choice", choices=tuple(Interaction.KINDS)),
                Field("event", "Event", "event"),
                Field("centre", "Centre", "centre__name"),
                Field("day", "Date", "day", "date"),
                Field("month", "Month", "month", "date", filterable=False),
                Field("actor", "Staff", "actor__username"),
                Field("member_number", "Member no.", "member__member_number", sensitivity="personal", groupable=False),
            ],
        ),
    }


_CACHE = {}


def datasets():
    if not _CACHE:
        _CACHE.update(_build())
    return _CACHE


def get(key):
    return datasets().get(key)


# --- running a report definition ---------------------------------------------------------------
class ReportError(ValueError):
    """A definition that cannot run (unknown field, value of the wrong type, column not allowed for this user)."""


def _parse_value(f, raw):
    raw = (raw or "").strip()
    if f.type == "bool":
        return None
    if f.type == "date":
        try:
            return date.fromisoformat(raw)
        except ValueError as exc:
            raise ReportError(f"{f.label}: enter a date as YYYY-MM-DD.") from exc
    if f.type == "number":
        try:
            return int(raw)
        except ValueError as exc:
            raise ReportError(f"{f.label}: enter a whole number.") from exc
    if f.type == "duration":
        try:
            return timedelta(minutes=float(raw))
        except ValueError as exc:
            raise ReportError(f"{f.label}: enter a number of minutes.") from exc
    if f.type == "choice" and f.choices and raw not in {c[0] for c in f.choices}:
        raise ReportError(f"{f.label}: choose one of the listed values.")
    if not raw:
        raise ReportError(f"{f.label}: enter a value to filter on.")
    return raw[:120]


def apply_filters(ds, qs, filters, user):
    fm = ds.field_map()
    for flt in filters or []:
        f = fm.get(flt.get("field"))
        op = flt.get("op")
        if f is None or not f.filterable:
            raise ReportError("A filter uses a field this dataset does not offer.")
        if not can_see(user, f.sensitivity):
            raise ReportError(f"Your role cannot filter on {f.label}.")
        if op not in OPS_BY_TYPE[f.type]:
            raise ReportError(f"{f.label}: that comparison is not available.")
        value = _parse_value(f, flt.get("value"))
        if op == "yes":
            qs = qs.filter(**{f.lookup: True})
        elif op == "no":
            qs = qs.filter(**{f.lookup: False})
        elif op == "eq":
            qs = qs.filter(**{f.lookup: value})
        elif op == "ne":
            qs = qs.exclude(**{f.lookup: value})
        elif op == "contains":
            qs = qs.filter(**{f"{f.lookup}__icontains": value})
        elif op == "gte":
            qs = qs.filter(**{f"{f.lookup}__gte": value})
        elif op == "lte":
            qs = qs.filter(**{f"{f.lookup}__lte": value})
    return qs


def display(f, value):
    """A cell as people read it: choice labels, masked TRN, minutes for durations, plain dates."""
    if value is None or value == "":
        return ""
    if f.mask == "trn":
        return mask_trn(value)
    if f.type == "choice" and f.choices:
        return dict(f.choices).get(value, value)
    if f.type == "bool":
        return "Yes" if value else "No"
    if f.type == "duration" and isinstance(value, timedelta):
        return round(value.total_seconds() / 60, 1)
    if isinstance(value, datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        return value.strftime("%Y-%m") if f.key.endswith("month") else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, date):
        return value.strftime("%Y-%m") if f.key.endswith("month") else value.isoformat()
    return value


MEASURES = {"count": "Number of records"}


def measure_options(ds, user):
    opts = [("count", "Number of records")]
    for f in ds.visible_fields(user):
        if f.type in ("duration", "number"):
            opts.append((f"avg:{f.key}", f"Average {f.label.lower()}" + (" (minutes)" if f.type == "duration" else "")))
    return opts


def run(defn, user, *, row_limit=None):
    """Run a builder definition. Returns (headers, rows, truncated).

    defn = {"dataset", "columns": [keys], "filters": [{field, op, value}], "group_by": [keys], "measure": "count"|"avg:<key>"}
    With group_by the result is one row per group with its measure; without it, one row per record.
    """
    ds = get(defn.get("dataset"))
    if ds is None:
        raise ReportError("Choose a dataset.")
    fm = ds.field_map()
    group_by = [k for k in defn.get("group_by") or [] if k]
    columns = [k for k in defn.get("columns") or [] if k]
    for key in group_by + columns:
        f = fm.get(key)
        if f is None:
            raise ReportError("The report uses a field this dataset does not offer.")
        if not can_see(user, f.sensitivity):
            raise ReportError(f"Your role cannot see {f.label}.")
    qs = apply_filters(ds, ds.base(user), defn.get("filters"), user)
    limit = row_limit or 10000
    if group_by:
        for key in group_by:
            if not fm[key].groupable:
                raise ReportError(f"{fm[key].label} cannot be used to group (it is different on every record).")
        measure = defn.get("measure") or "count"
        lookups = [fm[k].lookup for k in group_by]
        if measure == "count":
            agg = Count("pk", distinct=True)
            label = "Number of records"
        elif measure.startswith("avg:") and measure[4:] in fm and fm[measure[4:]].type in ("duration", "number"):
            mf = fm[measure[4:]]
            if not can_see(user, mf.sensitivity):
                raise ReportError(f"Your role cannot see {mf.label}.")
            agg = Avg(mf.lookup)
            label = f"Average {mf.label.lower()}" + (" (minutes)" if mf.type == "duration" else "")
        else:
            raise ReportError("Choose what to count.")
        rows_qs = qs.values(*lookups).annotate(measure=agg).order_by("-measure", *lookups)
        raw = list(rows_qs[: limit + 1])
        truncated = len(raw) > limit
        headers = [fm[k].label for k in group_by] + [label]
        rows = []
        for r in raw[:limit]:
            m = r["measure"]
            if isinstance(m, timedelta):
                m = round(m.total_seconds() / 60, 1)
            elif isinstance(m, float):
                m = round(m, 1)
            rows.append([display(fm[k], r[fm[k].lookup]) for k in group_by] + [m])
        return headers, rows, truncated
    if not columns:
        raise ReportError("Choose at least one column, or something to group by.")
    lookups = [fm[k].lookup for k in columns]
    raw = list(qs.order_by("-pk").values_list(*lookups)[: limit + 1])
    truncated = len(raw) > limit
    headers = [fm[k].label for k in columns]
    rows = [[display(fm[k], v) for k, v in zip(columns, r, strict=True)] for r in raw[:limit]]
    return headers, rows, truncated


def is_aggregate(defn):
    return bool([k for k in defn.get("group_by") or [] if k])


def personal_columns(defn):
    ds = get(defn.get("dataset"))
    if ds is None:
        return []
    fm = ds.field_map()
    keys = [k for k in (defn.get("columns") or []) + (defn.get("group_by") or []) if k in fm]
    return [fm[k].label for k in keys if fm[k].sensitivity != "open"]


__all__ = ["OPS", "OPS_BY_TYPE", "Dataset", "Field", "ReportError", "datasets", "get", "run"]
