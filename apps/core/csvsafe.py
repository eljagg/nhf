"""CSV exports that cannot run formulas when opened in Excel (CSV / formula injection)."""

import re

DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


def cell(value):
    """Prefix text that a spreadsheet would treat as a formula with an apostrophe."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(DANGEROUS) else text


def row(values):
    return [cell(v) for v in values]


def filename(value):
    """Safe for a Content-Disposition header."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(value))[:120]
