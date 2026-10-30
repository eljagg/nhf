"""National identifiers other than the TRN: NIS number (format is a back-office parameter)."""

import re

from apps.core.models import Parameter

DEFAULT_NIS_PATTERN = r"^([A-Z][0-9]{6}|[0-9]{9})$"


def normalise_nis(value):
    """Upper-case, spaces and dashes removed."""
    return re.sub(r"[\s-]", "", value or "").upper()


def nis_pattern():
    """Current accepted format."""
    return str(Parameter.get("nis-format-regex", DEFAULT_NIS_PATTERN) or DEFAULT_NIS_PATTERN)


def is_valid_nis(value):
    """True for a blank value or one that matches the configured format."""
    value = normalise_nis(value)
    if not value:
        return True
    try:
        return bool(re.fullmatch(nis_pattern(), value))
    except re.error:
        return bool(re.fullmatch(DEFAULT_NIS_PATTERN, value))


def nis_owner(value, exclude_member_id=None):
    """The member who already holds this NIS number, if any."""
    from .models import Member

    value = normalise_nis(value)
    if not value:
        return None
    qs = Member.objects.filter(nis_number=value)
    if exclude_member_id:
        qs = qs.exclude(pk=exclude_member_id)
    return qs.first()
