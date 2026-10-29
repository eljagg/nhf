"""TRN/SRN screening and SRN approvals."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import PROCESS_ROLES, has_role, role_required
from apps.members.models import Member

from . import services
from .models import SrnIssue, TrnValidation


@role_required(*PROCESS_ROLES)
def screen(request):
    """TV10007 / SR10006: screen a TRN or SRN without a form."""
    number = services.clean_trn(request.GET.get("number", ""))
    result = None
    if number:
        if not services.is_valid_format(number):
            messages.error(request, "Enter nine digits.")
        elif number.startswith(str(services.Parameter.get("srn-prefix"))):
            issue = SrnIssue.objects.filter(srn=number).select_related("decided_by").first()
            result = {"kind": "srn", "issue": issue, "member": Member.objects.filter(trn=number).first()}
        else:
            validation = services.start_validation(number, user=request.user, purpose="screen")
            return redirect("identity:screen-result", pk=validation.pk)
    return render(request, "identity/screen.html", {"number": number, "result": result, "page_title": "TRN / SRN screening"})


@role_required(*PROCESS_ROLES)
def screen_result(request, pk):
    """Result page; polls while pending."""
    validation = get_object_or_404(TrnValidation, pk=pk, purpose="screen")
    member = Member.objects.filter(trn=validation.trn).first()
    template = "identity/_screen_result.html" if request.headers.get("HX-Request") else "identity/screen.html"
    return render(request, template, {"validation": validation, "member": member, "number": validation.trn, "page_title": "TRN screening"})


@role_required("customer_care", "supervisor", "manager", "srn_approver")
def srn_list(request):
    """Open and recent SRN requests."""
    open_issues = SrnIssue.objects.filter(status="requested").select_related("requested_by")
    recent = SrnIssue.objects.exclude(status="requested").select_related("requested_by", "decided_by")[:30]
    return render(
        request,
        "identity/srn_list.html",
        {"open_issues": open_issues, "recent": recent, "can_approve": has_role(request.user, "manager", "srn_approver"), "page_title": "SRN approvals"},
    )


@role_required("customer_care", "supervisor", "manager", "srn_approver")
def srn_detail(request, pk):
    """One request with its duplicate check."""
    issue = get_object_or_404(SrnIssue.objects.select_related("requested_by", "decided_by"), pk=pk)
    return render(
        request,
        "identity/srn_detail.html",
        {
            "issue": issue,
            "apps": issue.applications.all(),
            "can_approve": has_role(request.user, "manager", "srn_approver") and issue.status == "requested",
            "page_title": "SRN request",
        },
    )


@require_POST
@role_required("manager", "srn_approver")
def srn_decide(request, pk):
    """Approve or decline."""
    issue = get_object_or_404(SrnIssue, pk=pk, status="requested")
    note = request.POST.get("note", "").strip()
    if request.POST.get("decision") == "approve":
        try:
            services.approve_srn(issue, user=request.user, note=note)
            messages.success(request, f"SRN {issue.srn} issued.")
        except PermissionError as exc:
            messages.error(request, str(exc))
    else:
        if not note:
            messages.error(request, "Give a reason for declining.")
            return redirect("identity:srn-detail", pk=pk)
        services.decline_srn(issue, user=request.user, note=note)
        messages.success(request, "Request declined.")
    return redirect("identity:srn-detail", pk=pk)
