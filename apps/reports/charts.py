"""Charts drawn on the server as SVG: no third-party script (CSP stays 'self'), they print, and work in dark mode.

Colours come from CSS classes in frontend/app.css (.ch-*), so light and dark themes are handled there.
Every label is HTML-escaped before it goes into the SVG.
"""

import math
from html import escape

from django.utils.safestring import mark_safe


def _nice_step(raw):
    if raw <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 5, 10):
        if raw <= step * exp:
            return max(1, step * exp) if raw >= 1 else step * exp
    return 10 * exp


def _nice_max(value):
    """Top of the axis: four equal, whole steps for counts."""
    step = _nice_step(value / 4)
    return step * 4


def _fmt(v, unit=""):
    if isinstance(v, float) and not v.is_integer():
        text = f"{v:,.1f}"
    else:
        text = f"{int(v):,}"
    return f"{text}{unit}"


def bars(items, *, unit="", label_width=230, width=600, highlight=None, empty="No data for this period."):
    """Horizontal bars: items = [(label, value)], largest first as given."""
    items = [(str(lab), float(v or 0)) for lab, v in items]
    if not items or not any(v for _, v in items):
        return mark_safe(f'<p class="text-sm text-slate-500 py-4">{escape(empty)}</p>')  # noqa: S308 - escaped  # nosec B308 B703 - labels escaped; tested
    row, gap, top = 26, 6, 4
    height = top + len(items) * (row + gap)
    vmax = max(v for _, v in items)
    plot = width - label_width - 70
    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" style="max-width:100%;height:auto" role="img" aria-label="Bar chart">']
    for i, (lab, v) in enumerate(items):
        y = top + i * (row + gap)
        w = 0 if vmax == 0 else max(2, plot * v / vmax) if v else 0
        cls = "ch-bar-hi" if highlight and lab == highlight else "ch-bar"
        short = lab if len(lab) <= 36 else lab[:35] + "…"
        parts.append(f'<text x="{label_width - 8}" y="{y + row / 2 + 4}" text-anchor="end" class="ch-label"><title>{escape(lab)}</title>{escape(short)}</text>')
        parts.append(f'<rect x="{label_width}" y="{y + 3}" width="{w:.1f}" height="{row - 6}" rx="4" class="{cls}"/>')
        parts.append(f'<text x="{label_width + w + 6:.1f}" y="{y + row / 2 + 4}" class="ch-value">{escape(_fmt(v, unit))}</text>')
    parts.append("</svg>")
    return mark_safe("".join(parts))  # noqa: S308 - every label escaped above  # nosec B308 B703


def buckets(days):
    """Group a run of days for a time chart: by day up to 3 months, by week up to 13 months, then by month.

    Returns (labels, key) where key(date) gives the bucket a date belongs to and labels are in order.
    """
    from datetime import timedelta

    if len(days) <= 92:
        return [f"{d:%d %b}" for d in days], days, (lambda d: d)
    if len(days) <= 400:
        starts = sorted({d - timedelta(days=d.weekday()) for d in days})
        return [f"w/c {d:%d %b}" for d in starts], starts, (lambda d: d - timedelta(days=d.weekday()))
    starts = sorted({d.replace(day=1) for d in days})
    return [f"{d:%b %Y}" for d in starts], starts, (lambda d: d.replace(day=1))


def series_by(days, counts, keyfn, keys):
    """Sum per-day counts into the chart's buckets."""
    total = dict.fromkeys(keys, 0)
    for d in days:
        total[keyfn(d)] += counts.get(d, 0)
    return [total[k] for k in keys]


def lines(x_labels, series, *, width=640, height=230, unit="", target=None, target_label=""):
    """Line chart: series = [(name, [values aligned with x_labels])]. Up to 4 series."""
    if not x_labels or not series or not any(any(v for v in vals) for _, vals in series):
        return mark_safe('<p class="text-sm text-slate-500 py-4">No data for this period.</p>')  # noqa: S308  # nosec B308 B703 - constant text
    left, right, top, bottom = 46, 12, 12, 34
    pw, ph = width - left - right, height - top - bottom
    vmax = _nice_max(max([max(vals or [0]) for _, vals in series] + [target or 0]))
    n = len(x_labels)

    def X(i):
        return left + (pw * i / (n - 1) if n > 1 else pw / 2)

    def Y(v):
        return top + ph - ph * (v / vmax)

    parts = [f'<svg viewBox="0 0 {width} {height}" width="{width}" style="max-width:100%;height:auto" role="img" aria-label="Line chart">']
    for k in range(5):
        v = vmax * k / 4
        y = Y(v)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="ch-grid"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" text-anchor="end" class="ch-axis">{escape(_fmt(v, unit))}</text>')
    step = max(1, math.ceil(n / 8))
    for i, lab in enumerate(x_labels):
        if i % step == 0 or (i == n - 1 and (n - 1) % step >= step / 2):
            parts.append(f'<text x="{X(i):.1f}" y="{height - 12}" text-anchor="middle" class="ch-axis">{escape(str(lab))}</text>')
    if target:
        y = Y(target)
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y:.1f}" y2="{y:.1f}" class="ch-target"/>')
        parts.append(f'<text x="{width - right}" y="{y - 5:.1f}" text-anchor="end" class="ch-target-label">{escape(target_label)}</text>')
    for si, (_name, vals) in enumerate(series[:4]):
        pts = " ".join(f"{X(i):.1f},{Y(v or 0):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline points="{pts}" class="ch-line ch-s{si + 1}" fill="none"/>')
        for i, v in enumerate(vals):
            parts.append(
                f'<circle cx="{X(i):.1f}" cy="{Y(v or 0):.1f}" r="2.6" class="ch-dot ch-s{si + 1}"><title>{escape(str(x_labels[i]))}: {escape(_fmt(v or 0, unit))}</title></circle>'
            )
    parts.append("</svg>")
    legend = "".join(
        f'<span class="inline-flex items-center gap-1.5 mr-4"><span class="ch-key ch-s{i + 1}"></span>{escape(name)}</span>'
        for i, (name, _) in enumerate(series[:4])
    )
    return mark_safe(f'<div class="text-xs text-slate-600 dark:text-slate-300 mb-1">{legend}</div>' + "".join(parts))  # noqa: S308 - escaped  # nosec B308 B703 - labels escaped; tested
