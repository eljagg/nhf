"""NHF Doctors register and MCJ confirmation queue."""

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import has_role, role_required
from apps.core import audit
from apps.members.models import Application

from . import services
from .models import Doctor

VIEW_ROLES = ("customer_care", "supervisor", "manager", "mcj_confirmer")


class DoctorForm(forms.ModelForm):
    """DV10005: Customer Care maintains doctor profiles (the MCJ number itself is fixed)."""

    class Meta:
        model = Doctor
        fields = ["title", "first_name", "last_name", "specialty", "practice_name", "parish", "phone", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "inp")


@role_required(*VIEW_ROLES)
def doctor_list(request):
    """Search the register."""
    q = request.GET.get("q", "").strip()
    qs = Doctor.objects.all()
    if q:
        qs = qs.filter(Q(mcj_number__iexact=q) | Q(last_name__istartswith=q) | Q(first_name__istartswith=q) | Q(practice_name__icontains=q))
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "doctors/list.html", {"page": page, "q": q, "page_title": "NHF Doctors register"})


@role_required(*VIEW_ROLES)
def doctor_detail(request, mcj):
    """Profile; editable by Customer Care."""
    doctor = get_object_or_404(Doctor, mcj_number=mcj)
    form = DoctorForm(request.POST or None, instance=doctor)
    if request.method == "POST" and has_role(request.user, "customer_care", "supervisor", "manager") and form.is_valid():
        form.save()
        audit.record("doctor.updated", doctor, f"Doctor profile {doctor.mcj_number} updated", fields=list(form.changed_data))
        messages.success(request, "Doctor profile saved.")
        return redirect("doctors:detail", mcj=mcj)
    apps = Application.objects.filter(doctor=doctor).select_related("centre")[:20]
    return render(request, "doctors/detail.html", {"doctor": doctor, "form": form, "apps": apps, "page_title": str(doctor)})


@role_required("manager", "mcj_confirmer", "supervisor")
def confirmations(request):
    """DV10003: unknown MCJ numbers waiting for confirmation with the Medical Council."""
    pending = Doctor.objects.filter(status="pending").order_by("created_at")
    rows = [{"d": d, "apps": Application.objects.filter(doctor=d, status__in=Application.OPEN_STATUSES)} for d in pending]
    return render(
        request,
        "doctors/confirmations.html",
        {"rows": rows, "can_decide": has_role(request.user, "manager", "mcj_confirmer"), "page_title": "MCJ confirmations"},
    )


@require_POST
@role_required("manager", "mcj_confirmer")
def decide(request, mcj):
    """Record the MCJ's answer."""
    doctor = get_object_or_404(Doctor, mcj_number=mcj, status="pending")
    note = request.POST.get("note", "").strip()
    if request.POST.get("decision") == "confirm":
        services.confirm(
            doctor, user=request.user, note=note, first_name=request.POST.get("first_name", "").strip(), last_name=request.POST.get("last_name", "").strip()
        )
        for app in Application.objects.filter(doctor=doctor, status__in=Application.OPEN_STATUSES):
            from apps.members.services import refresh_status

            refresh_status(app)
        messages.success(request, f"MCJ {mcj} confirmed and added to the register.")
    else:
        if not note:
            messages.error(request, "Record what the Medical Council said.")
            return redirect("doctors:confirmations")
        rejected = services.reject(doctor, user=request.user, note=note)
        messages.success(request, f"MCJ {mcj} not confirmed; {len(rejected)} application(s) rejected.")
    return redirect("doctors:confirmations")
