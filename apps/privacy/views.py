"""Data Protection Act 2020 module: dashboard, data-subject requests, breach register, processing register, retention."""

import json
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.roles import has_role, role_required
from apps.core import audit
from apps.core.models import Parameter
from apps.core.notifications import notify_role
from apps.members.identifiers import normalise_nis
from apps.members.models import Application, Member

from . import services
from .forms import BreachForm, DsrForm, DsrUpdateForm, ImpactAssessmentForm
from .models import Breach, DataSubjectRequest, ImpactAssessment, ProcessingActivity, RetentionRun

VIEW_ROLES = ("dpo", "manager", "auditor")
EDIT_ROLES = ("dpo", "manager")


@role_required(*VIEW_ROLES)
def dashboard(request):
    """Open requests and breaches with their clocks, consent coverage, retention status."""
    members = Member.objects.count()
    with_consent = Member.objects.filter(consent_at__isnull=False).count()
    candidates = services.retention_candidates()
    ctx = {
        "dsrs": DataSubjectRequest.objects.filter(status__in=("open", "in_progress")).select_related("member")[:20],
        "breaches": Breach.objects.exclude(status="closed")[:20],
        "members": members,
        "with_consent": with_consent,
        "consent_pct": round(100 * with_consent / members, 1) if members else 100,
        "open_without_consent": Application.objects.filter(status__in=Application.OPEN_STATUSES, consent_given=False).count(),
        "retention_due": {k: qs.count() for k, qs in candidates.items()},
        "last_run": RetentionRun.objects.filter(dry_run=False).first(),
        "activities": ProcessingActivity.objects.count(),
        "notice_version": Parameter.get("privacy-notice-version"),
        "registration": _registration_status(),
        "dpia": ImpactAssessment.objects.filter(year=timezone.localdate().year).first(),
        "year": timezone.localdate().year,
        "restricted": Member.objects.filter(processing_restricted_at__isnull=False).count(),
        "dpo_set": bool(Parameter.get("dpo-name") and (Parameter.get("dpo-email") or Parameter.get("dpo-phone"))),
        "can_edit": has_role(request.user, *EDIT_ROLES),
        "page_title": "Data protection",
    }
    return render(request, "privacy/dashboard.html", ctx)


def _registration_status():
    """Registration with the Information Commissioner: number set, and how long until renewal."""
    from datetime import date

    number = Parameter.get("dpa-registration-number")
    expiry_raw = Parameter.get("dpa-registration-expiry")
    try:
        expiry = date.fromisoformat(str(expiry_raw)) if expiry_raw else None
    except ValueError:
        expiry = None
    days = (expiry - timezone.localdate()).days if expiry else None
    return {"number": number, "expiry": expiry, "days": days, "warn": not number or days is None or days <= 60}


def _find_member(value):
    value = (value or "").strip()
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    nis = normalise_nis(value)
    query = Q()
    if len(digits) >= 9:  # member numbers are 10 digits, TRNs 9
        query |= Q(member_number=digits) | Q(trn=digits)
    if nis and len(nis) >= 7:
        query |= Q(nis_number=nis)
    if not query:
        return None
    matches = list(Member.objects.filter(query)[:2])
    return matches[0] if len(matches) == 1 else None  # ambiguous: link by member number instead


@role_required(*VIEW_ROLES)
def dsr_list(request):
    """All data-subject requests."""
    form = DsrForm(request.POST or None)
    if request.method == "POST":
        if not has_role(request.user, *EDIT_ROLES):
            return redirect("privacy:dsr-list")
        if form.is_valid():
            dsr = form.save(commit=False)
            dsr.member = _find_member(form.cleaned_data.get("member_lookup"))
            dsr.due_at = dsr.received_at + timedelta(days=int(Parameter.get("dsr-days")))
            dsr.logged_by = request.user
            dsr.save()
            audit.record("privacy.dsr_logged", dsr, f"{dsr.reference} logged: {dsr.get_kind_display()} from {dsr.requester_name}")
            notify_role(
                "dpo",
                "dsr-received",
                obj=dsr,
                link=f"/privacy/requests/{dsr.pk}/",
                reference=dsr.reference,
                kind=dsr.get_kind_display(),
                name=dsr.requester_name,
                due=timezone.localtime(dsr.due_at).strftime("%d %b %Y"),
            )
            if dsr.member is None and form.cleaned_data.get("member_lookup"):
                messages.warning(request, "No member matched that number; link the member on the request once found.")
            messages.success(request, f"{dsr.reference} logged. Answer due {timezone.localtime(dsr.due_at):%d %b %Y}.")
            return redirect("privacy:dsr-detail", pk=dsr.pk)
    rows = DataSubjectRequest.objects.select_related("member", "handled_by")
    return render(
        request, "privacy/dsr_list.html", {"rows": rows, "form": form, "can_edit": has_role(request.user, *EDIT_ROLES), "page_title": "Data-subject requests"}
    )


@role_required(*VIEW_ROLES)
def dsr_detail(request, pk):
    """One request: status, response, export."""
    dsr = get_object_or_404(DataSubjectRequest.objects.select_related("member"), pk=pk)
    form = DsrUpdateForm(request.POST or None, instance=dsr)
    if request.method == "POST" and has_role(request.user, *EDIT_ROLES):
        if request.POST.get("restrict") or request.POST.get("lift"):
            if dsr.member is None:
                messages.error(request, "Link the request to a member first.")
            elif request.POST.get("restrict"):
                reason = request.POST.get("reason", "").strip() or f"{dsr.get_kind_display()} {dsr.reference}"
                services.restrict_processing(dsr.member, reason=f"{reason} ({dsr.reference})", user=request.user, dsr=dsr)
                messages.success(
                    request, f"Processing of member {dsr.member.member_number} restricted. Their applications cannot be approved until it is lifted."
                )
            else:
                services.lift_restriction(dsr.member, note=request.POST.get("reason", "").strip() or dsr.reference, user=request.user, dsr=dsr)
                messages.success(request, "Restriction lifted.")
            return redirect("privacy:dsr-detail", pk=pk)
        if request.POST.get("link_member"):
            member = _find_member(request.POST["link_member"])
            if member:
                dsr.member = member
                dsr.save(update_fields=["member"])
                messages.success(request, f"Linked to member {member.member_number}.")
            else:
                messages.error(request, "No member matched.")
            return redirect("privacy:dsr-detail", pk=pk)
        if form.is_valid():
            dsr = form.save(commit=False)
            dsr.handled_by = dsr.handled_by or request.user
            if dsr.status in ("completed", "refused") and not dsr.completed_at:
                dsr.completed_at = timezone.now()
            dsr.save()
            audit.record("privacy.dsr_updated", dsr, f"{dsr.reference} → {dsr.get_status_display()}", fields=list(form.changed_data))
            messages.success(request, "Request updated.")
            return redirect("privacy:dsr-detail", pk=pk)
    return render(request, "privacy/dsr_detail.html", {"dsr": dsr, "form": form, "can_edit": has_role(request.user, *EDIT_ROLES), "page_title": dsr.reference})


@role_required(*EDIT_ROLES)
def dsr_export(request, pk):
    """Download the member's data as JSON for an access request."""
    dsr = get_object_or_404(DataSubjectRequest.objects.select_related("member"), pk=pk)
    if dsr.member is None:
        messages.error(request, "Link the request to a member first.")
        return redirect("privacy:dsr-detail", pk=pk)
    if not dsr.identity_checked:
        messages.error(request, "Confirm the requester's identity before releasing a copy of the data.")
        return redirect("privacy:dsr-detail", pk=pk)
    data = services.member_export(dsr.member)
    services.record_export(dsr, user=request.user)
    response = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json")
    response["Content-Disposition"] = f'attachment; filename="{dsr.reference}-{dsr.member.member_number}.json"'
    return response


@role_required(*VIEW_ROLES)
def breach_list(request):
    """Breach register."""
    form = BreachForm(request.POST or None, initial={"discovered_at": timezone.localtime().strftime("%Y-%m-%dT%H:%M")})
    if request.method == "POST" and has_role(request.user, *EDIT_ROLES) and form.is_valid():
        breach = form.save(commit=False)
        breach.logged_by = request.user
        breach.save()
        audit.record("privacy.breach_logged", breach, f"{breach.reference} logged: {breach.title}")
        deadline = timezone.localtime(breach.report_deadline).strftime("%d %b %Y %H:%M")
        for role in ("dpo", "manager"):
            notify_role(
                role, "breach-logged", obj=breach, link=f"/privacy/breaches/{breach.pk}/", reference=breach.reference, title=breach.title, deadline=deadline
            )
        messages.success(request, f"{breach.reference} logged. Report to the Information Commissioner by {deadline}.")
        return redirect("privacy:breach-detail", pk=breach.pk)
    return render(
        request,
        "privacy/breach_list.html",
        {"rows": Breach.objects.all(), "form": form, "can_edit": has_role(request.user, *EDIT_ROLES), "page_title": "Breach register"},
    )


@role_required(*VIEW_ROLES)
def breach_detail(request, pk):
    """Update a breach as it is contained and reported."""
    breach = get_object_or_404(Breach, pk=pk)
    form = BreachForm(request.POST or None, instance=breach)
    if request.method == "POST" and has_role(request.user, *EDIT_ROLES) and form.is_valid():
        form.save()
        audit.record("privacy.breach_updated", breach, f"{breach.reference} updated → {breach.get_status_display()}", fields=list(form.changed_data))
        messages.success(request, "Breach record updated.")
        return redirect("privacy:breach-detail", pk=pk)
    return render(
        request, "privacy/breach_detail.html", {"b": breach, "form": form, "can_edit": has_role(request.user, *EDIT_ROLES), "page_title": breach.reference}
    )


@role_required(*VIEW_ROLES)
def register(request):
    """Record of processing activities."""
    return render(request, "privacy/register.html", {"rows": ProcessingActivity.objects.all(), "page_title": "Processing register"})


@require_POST
@role_required("dpo", "ict_admin")
def retention_run(request):
    """Run the retention sweep now (or preview it)."""
    dry = request.POST.get("dry_run") == "1"
    run = services.run_retention(dry_run=dry, user=request.user)
    messages.success(request, ("Preview: " if dry else "Retention sweep done: ") + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in run.results.items()))
    return redirect("privacy:dashboard")


@role_required(*VIEW_ROLES)
def breach_notice(request, pk, audience):
    """Draft notice to the Information Commissioner or to the people affected, as plain text to paste into the portal or a letter."""
    if audience not in ("commissioner", "subjects"):
        raise Http404
    breach = get_object_or_404(Breach, pk=pk)
    audit.record("privacy.breach_notice_drafted", breach, f"{breach.reference}: notice to {audience} drafted")
    resp = HttpResponse(services.breach_notice(breach, audience), content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{breach.reference}-notice-{audience}.txt"'
    return resp


@role_required(*VIEW_ROLES)
def dpia_list(request):
    """Annual impact assessments."""
    year = timezone.localdate().year
    if request.method == "POST" and has_role(request.user, *EDIT_ROLES) and request.POST.get("start"):
        dpia, created = ImpactAssessment.objects.get_or_create(year=year, defaults={**services.draft_impact_assessment(year), "created_by": request.user})
        if created:
            audit.record("privacy.dpia_started", dpia, f"Impact assessment {year} started")
        return redirect("privacy:dpia-detail", year=year)
    return render(
        request,
        "privacy/dpia_list.html",
        {
            "rows": ImpactAssessment.objects.all(),
            "year": year,
            "has_current": ImpactAssessment.objects.filter(year=year).exists(),
            "can_edit": has_role(request.user, *EDIT_ROLES),
            "page_title": "Impact assessments",
        },
    )


@role_required(*VIEW_ROLES)
def dpia_detail(request, year):
    dpia = get_object_or_404(ImpactAssessment, year=year)
    can_edit = has_role(request.user, *EDIT_ROLES) and dpia.status != "submitted"
    form = ImpactAssessmentForm(request.POST or None, instance=dpia)
    if request.method == "POST" and can_edit:
        action = request.POST.get("action", "save")
        if action == "approve" and has_role(request.user, "dpo"):
            dpia.status, dpia.approved_by, dpia.approved_at = "approved", request.user, timezone.now()
            dpia.save()
            audit.record("privacy.dpia_approved", dpia, f"Impact assessment {year} approved")
            messages.success(request, "Approved.")
        elif action == "submitted" and dpia.status == "approved":
            dpia.status, dpia.submitted_at = "submitted", timezone.now()
            dpia.save()
            audit.record("privacy.dpia_submitted", dpia, f"Impact assessment {year} recorded as submitted to the Information Commissioner")
            messages.success(request, "Recorded as submitted to the Information Commissioner.")
        elif action == "save" and form.is_valid():
            dpia = form.save(commit=False)
            dpia.status = "draft"
            dpia.save()
            audit.record("privacy.dpia_updated", dpia, f"Impact assessment {year} edited", fields=list(form.changed_data))
            messages.success(request, "Saved as draft.")
        return redirect("privacy:dpia-detail", year=year)
    if not can_edit:
        for f in form.fields.values():
            f.disabled = True
    return render(
        request,
        "privacy/dpia_detail.html",
        {"d": dpia, "form": form, "can_edit": can_edit, "is_dpo": has_role(request.user, "dpo"), "page_title": f"Impact assessment {year}"},
    )
