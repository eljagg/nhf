"""Dashboards, standard reports, the report builder, saved reports and schedules."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.roles import role_required
from apps.core import audit, ratelimit
from apps.core.models import Parameter

from . import datasets, export, metrics, standard
from .access import REPORT_ROLES, can_see
from .filters import period_from
from .forms import SaveReportForm, ScheduleForm
from .models import ReportSchedule, SavedReport

MAX_FILTERS = 4
PREVIEW_ROWS = 200


def _meta(user, period=None, extra=()):
    lines = [f"Produced {timezone.localtime():%d %b %Y %H:%M} by {user.username}"]
    if period is not None:
        lines.append(f"Period: {period.start_date:%d %b %Y} – {period.end_date:%d %b %Y}")
        if period.centre:
            lines.append(f"Centre: {period.centre.name}")
        if period.channel:
            lines.append(f"Channel: {period.channel}")
    lines.extend(extra)
    lines.append("Contains NHF information. Handle under the Data Protection Act 2020; do not forward outside NHF.")
    return lines


def _export_allowed(request):
    return ratelimit.enforce(request, "report-export", "limit-report-exports-per-hour", "report exports")


# --- dashboard -------------------------------------------------------------------------------------
@role_required(*REPORT_ROLES)
def dashboard(request):
    period, form = period_from(request.GET, request.user)
    from django.utils.http import urlencode

    ctx = {"period": period, "form": form, "qs": urlencode(period.as_query()), "page_title": "Dashboard", **metrics.dashboard(period)}
    if request.headers.get("HX-Request"):
        return render(request, "reports/_dashboard_body.html", ctx)
    return render(request, "reports/dashboard.html", ctx)


# --- standard reports ------------------------------------------------------------------------------
@role_required(*REPORT_ROLES)
def catalogue(request):
    saved = SavedReport.objects.filter(Q(owner=request.user) | Q(shared=True)).select_related("owner").prefetch_related("schedules")
    return render(
        request,
        "reports/catalogue.html",
        {"reports": standard.available(request.user), "saved": saved, "page_title": "Reports"},
    )


@role_required(*REPORT_ROLES)
def standard_report(request, key):
    if key not in standard.CATALOGUE:
        raise Http404
    period, form = period_from(request.GET, request.user)
    try:
        report = standard.build(key, period, request.user)
    except PermissionError as exc:
        raise PermissionDenied from exc
    fmt = request.GET.get("format")
    if fmt in ("csv", "xlsx"):
        if not _export_allowed(request):
            messages.error(request, "Export limit reached for this hour. Try again later.")
            return redirect(request.path)
        audit.record("report.exported", None, f"Standard report '{report.title}' exported as {fmt}", report=key, **period.as_query())
        sections = [(t.title, t.headers, t.rows) for t in report.tables]
        return export.response(sections, title=report.title, meta=_meta(request.user, period), fmt=fmt, stem=f"nhf-{key}")
    audit.record("report.viewed", None, f"Standard report '{report.title}' viewed", report=key, **period.as_query())
    query = request.GET.copy()
    query.pop("format", None)
    return render(
        request,
        "reports/standard.html",
        {
            "report": report,
            "period": period,
            "form": form,
            "query": query.urlencode(),
            "save_form": SaveReportForm(),
            "page_title": report.title,
        },
    )


@require_POST
@role_required(*REPORT_ROLES)
def save_standard(request, key):
    if key not in standard.CATALOGUE or not can_see(request.user, standard.CATALOGUE[key][2]):
        raise Http404
    form = SaveReportForm(request.POST)
    if form.is_valid():
        filters = {k: request.POST.get(k, "") for k in ("preset", "centre", "channel") if request.POST.get(k)}
        report = SavedReport.objects.create(
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
            kind="standard",
            standard_key=key,
            definition=filters,
            owner=request.user,
            shared=form.cleaned_data["shared"],
        )
        audit.record("report.saved", report, f"Saved report '{report.name}'")
        messages.success(request, f"Saved as '{report.name}'. You can schedule it from Reports.")
    else:
        messages.error(request, "Give the report a name.")
    return redirect(reverse("reports:standard", args=[key]))


# --- report builder --------------------------------------------------------------------------------
def _definition_from(data):
    defn = {
        "dataset": data.get("dataset", ""),
        "columns": [c for c in data.getlist("col") if c],
        "group_by": [g for g in data.getlist("group") if g][:2],
        "measure": data.get("measure") or "count",
        "filters": [],
    }
    for i in range(MAX_FILTERS):
        fld = data.get(f"f{i}_field")
        if fld:
            defn["filters"].append({"field": fld, "op": data.get(f"f{i}_op", ""), "value": data.get(f"f{i}_value", "")})
    return defn


def _builder_context(request, defn, *, saved=None):
    ds = datasets.get(defn.get("dataset")) or datasets.get("applications")
    defn["dataset"] = ds.key
    fields = ds.visible_fields(request.user)
    filter_rows = list(defn.get("filters") or [])
    filter_rows += [{"field": "", "op": "", "value": ""}] * (MAX_FILTERS - len(filter_rows))
    return {
        "datasets": [(d.key, d.label, d.description) for d in datasets.datasets().values()],
        "ds": ds,
        "fields": fields,
        "groupable": [f for f in fields if f.groupable],
        "filterable": [f for f in fields if f.filterable],
        "ops": datasets.OPS,
        "ops_by_type": datasets.OPS_BY_TYPE,
        "measures": datasets.measure_options(ds, request.user),
        "defn": defn,
        "filter_rows": filter_rows[:MAX_FILTERS],
        "group_slots": (defn.get("group_by") or []) + [""] * (2 - len(defn.get("group_by") or [])),
        "saved": saved,
        "save_form": SaveReportForm(initial={"name": saved.name, "description": saved.description, "shared": saved.shared} if saved else None),
        "page_title": "Report builder",
    }


@role_required(*REPORT_ROLES)
def builder(request, pk=None):
    saved = None
    if pk is not None:
        saved = get_object_or_404(SavedReport, Q(owner=request.user) | Q(shared=True), pk=pk, kind="builder")
        defn = dict(saved.definition)
        if request.GET.get("run") or request.GET.get("format"):
            defn = _definition_from(request.GET) if request.GET.get("dataset") else defn
    else:
        defn = _definition_from(request.GET) if request.GET.get("dataset") else {"dataset": "applications", "group_by": ["channel"], "measure": "count"}
    ctx = _builder_context(request, defn, saved=saved)
    run = request.GET.get("run") or request.GET.get("format") or (saved is not None and not request.GET)
    if run:
        limit = int(Parameter.get("report-row-limit"))
        try:
            headers, rows, truncated = datasets.run(defn, request.user, row_limit=limit)
        except datasets.ReportError as exc:
            ctx["error"] = str(exc)
            return render(request, "reports/builder.html", ctx)
        fmt = request.GET.get("format")
        title = saved.name if saved else f"{ctx['ds'].label} report"
        personal = datasets.personal_columns(defn)
        if fmt in ("csv", "xlsx"):
            if not _export_allowed(request):
                ctx["error"] = "Export limit reached for this hour. Try again later."
                return render(request, "reports/builder.html", ctx)
            audit.record(
                "report.exported",
                saved,
                f"Report '{title}' exported as {fmt} ({len(rows)} rows)" + (f"; personal columns: {', '.join(personal)}" if personal else ""),
                definition=defn,
                rows=len(rows),
            )
            extra = [f"Cut off at {limit:,} rows."] if truncated else []
            return export.response([("", headers, rows)], title=title, meta=_meta(request.user, extra=extra), fmt=fmt, stem="nhf-report")
        audit.record("report.run", saved, f"Report '{title}' run ({len(rows)} rows)", definition=defn, rows=len(rows))
        ctx.update({"headers": headers, "rows": rows[:PREVIEW_ROWS], "row_count": len(rows), "truncated": truncated, "limit": limit, "personal": personal})
        query = request.GET.copy()
        query.pop("format", None)
        query["run"] = "1"
        if saved and "dataset" not in query:
            query = None
        ctx["query"] = query.urlencode() if query else ""
    return render(request, "reports/builder.html", ctx)


@require_POST
@role_required(*REPORT_ROLES)
def builder_save(request, pk=None):
    defn = _definition_from(request.POST)
    try:
        datasets.run(defn, request.user, row_limit=1)  # refuses fields the user may not use
    except datasets.ReportError as exc:
        messages.error(request, f"Not saved: {exc}")
        return redirect(reverse("reports:builder"))
    form = SaveReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Give the report a name.")
        return redirect(reverse("reports:builder"))
    if pk is not None:
        report = get_object_or_404(SavedReport, pk=pk, owner=request.user, kind="builder")
        report.definition, report.name = defn, form.cleaned_data["name"]
        report.description, report.shared = form.cleaned_data["description"], form.cleaned_data["shared"]
        report.save()
        if not report.aggregate_only:
            ReportSchedule.objects.filter(report=report).update(active=False)
    else:
        report = SavedReport.objects.create(
            name=form.cleaned_data["name"],
            description=form.cleaned_data["description"],
            kind="builder",
            definition=defn,
            owner=request.user,
            shared=form.cleaned_data["shared"],
        )
    audit.record("report.saved", report, f"Saved report '{report.name}'", definition=defn)
    messages.success(request, f"Saved '{report.name}'.")
    return redirect(reverse("reports:saved", args=[report.pk]))


@role_required(*REPORT_ROLES)
def saved(request, pk):
    report = get_object_or_404(SavedReport, Q(owner=request.user) | Q(shared=True), pk=pk)
    if report.kind == "standard":
        from django.http import QueryDict

        q = QueryDict(mutable=True)
        q.update(report.definition)
        return redirect(f"{reverse('reports:standard', args=[report.standard_key])}?{q.urlencode()}")
    return builder(request, pk=pk)


@require_POST
@role_required(*REPORT_ROLES)
def delete_saved(request, pk):
    report = get_object_or_404(SavedReport, pk=pk, owner=request.user)
    audit.record("report.deleted", report, f"Deleted saved report '{report.name}'")
    report.delete()
    messages.success(request, "Report deleted.")
    return redirect("reports:catalogue")


# --- schedules (NT10002) -------------------------------------------------------------------------------
@role_required(*REPORT_ROLES)
def schedule(request, pk):
    report = get_object_or_404(SavedReport, Q(owner=request.user) | Q(shared=True), pk=pk)
    if not report.aggregate_only:
        messages.error(request, "Only reports of counts can be e-mailed. Group this report by at least one field to schedule it.")
        return redirect("reports:catalogue")
    form = ScheduleForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        sched = form.save(commit=False)
        sched.report, sched.created_by = report, request.user
        sched.next_run_at = sched.compute_next_run()
        sched.save()
        form.save_m2m()
        audit.record("report.scheduled", sched, f"'{report.name}' scheduled {sched.get_frequency_display().lower()} to {sched.recipients.count()} recipient(s)")
        messages.success(request, f"Scheduled. First e-mail {timezone.localtime(sched.next_run_at):%a %d %b at %H:%M}.")
        return redirect("reports:catalogue")
    return render(
        request,
        "reports/schedule.html",
        {"report": report, "form": form, "schedules": report.schedules.prefetch_related("recipients"), "page_title": f"Schedule {report.name}"},
    )


@require_POST
@role_required(*REPORT_ROLES)
def schedule_stop(request, pk):
    sched = get_object_or_404(ReportSchedule, Q(created_by=request.user) | Q(report__owner=request.user), pk=pk)
    sched.active = False
    sched.save(update_fields=["active"])
    audit.record("report.schedule_stopped", sched, f"Stopped schedule for '{sched.report.name}'")
    messages.success(request, "Schedule stopped.")
    return redirect("reports:catalogue")


@require_POST
@role_required(*REPORT_ROLES)
def schedule_send_now(request, pk):
    sched = get_object_or_404(ReportSchedule, Q(created_by=request.user) | Q(report__owner=request.user), pk=pk, active=True)
    from .scheduling import send_schedule

    result = send_schedule(sched, manual=True)
    messages.success(request, result)
    return redirect("reports:catalogue")
