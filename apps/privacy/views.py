"""Data Protection Act 2020 module: dashboard, data-subject requests, breach register, processing register, retention."""

import json
from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
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
from .forms import BreachForm, DsrForm, DsrUpdateForm
from .models import Breach, DataSubjectRequest, ProcessingActivity, RetentionRun

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
        "can_edit": has_role(request.user, *EDIT_ROLES),
        "page_title": "Data protection",
    }
    return render(request, "privacy/dashboard.html", ctx)


def _find_member(value):
    value = (value or "").strip()
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return Member.objects.filter(Q(member_number=digits) | Q(trn=digits) | Q(nis_number=normalise_nis(value))).first() if value else None


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
