"""NHF Doctors and Nurses registers, council register checks, confirmation queue and register import."""

import csv
import io

from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.roles import has_role, role_required
from apps.core import audit, images
from apps.core.models import IntegrationRun
from apps.members.models import Application

from . import registers, services
from .models import COUNCILS, CouncilRegisterEntry, Doctor, Nurse
from .verification import practitioner_link, verify

VIEW_ROLES = ("customer_care", "supervisor", "manager", "mcj_confirmer", "auditor")
EDIT_ROLES = ("customer_care", "supervisor", "manager", "mcj_confirmer")
DECIDE_ROLES = ("manager", "mcj_confirmer")
ADDRESS_FIELDS = ["practice_name", "address_line1", "address_line2", "town", "parish", "phone", "email"]


class _Styled(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "inp")


class DoctorForm(_Styled):
    """DV10005: Customer Care maintains doctor profiles (the MCJ number itself is fixed)."""

    class Meta:
        model = Doctor
        fields = ["title", "first_name", "last_name", "specialty", *ADDRESS_FIELDS]


class NurseForm(_Styled):
    class Meta:
        model = Nurse
        fields = ["title", "first_name", "last_name", "category", *ADDRESS_FIELDS]


class AddNurseForm(_Styled):
    class Meta:
        model = Nurse
        fields = ["ncj_number", "first_name", "last_name", "category", *ADDRESS_FIELDS]


def _search(qs, q, number_field):
    if q:
        qs = qs.filter(
            Q(**{f"{number_field}__iexact": q})
            | Q(last_name__istartswith=q)
            | Q(first_name__istartswith=q)
            | Q(practice_name__icontains=q)
            | Q(town__istartswith=q)
        )
    return qs


@role_required(*VIEW_ROLES)
def doctor_list(request):
    """Search the doctors register."""
    q = request.GET.get("q", "").strip()
    qs = _search(Doctor.objects.select_related("photo"), q, "mcj_number")
    if request.GET.get("concern"):
        qs = qs.filter(status="confirmed", register_status__in=["lapsed", "suspended", "removed", "not_found"])
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "doctors/list.html", {"page": page, "q": q, "concern": request.GET.get("concern"), "page_title": "NHF Doctors register"})


def _profile(request, practitioner, form_class):
    form = form_class(request.POST or None, instance=practitioner)
    can_edit = has_role(request.user, *EDIT_ROLES)
    if request.method == "POST" and can_edit and form.is_valid():
        form.save()
        audit.record(f"{practitioner._meta.model_name}.updated", practitioner, f"Profile of {practitioner} updated", fields=list(form.changed_data))
        messages.success(request, "Profile saved.")
        return redirect(practitioner_link(practitioner))
    if not can_edit:
        for f in form.fields.values():
            f.disabled = True
    return form, can_edit


@role_required(*VIEW_ROLES)
def doctor_detail(request, mcj):
    """Profile with practice location, photo and council register status; editable by Customer Care."""
    doctor = get_object_or_404(Doctor, mcj_number=mcj)
    result = _profile(request, doctor, DoctorForm)
    if not isinstance(result, tuple):
        return result
    form, can_edit = result
    apps = Application.objects.filter(doctor=doctor).select_related("centre")[:20]
    return render(
        request,
        "doctors/detail.html",
        {"p": doctor, "kind": "doctor", "form": form, "apps": apps, "can_edit": can_edit, "council": "Medical Council", "page_title": str(doctor)},
    )


@role_required(*VIEW_ROLES)
def nurse_list(request):
    q = request.GET.get("q", "").strip()
    qs = _search(Nurse.objects.select_related("photo"), q, "ncj_number")
    if request.GET.get("concern"):
        qs = qs.filter(status="confirmed", register_status__in=["lapsed", "suspended", "removed", "not_found"])
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "doctors/nurse_list.html", {"page": page, "q": q, "concern": request.GET.get("concern"), "page_title": "Nurses register"})


@role_required(*VIEW_ROLES)
def nurse_detail(request, ncj):
    nurse = get_object_or_404(Nurse, ncj_number=ncj)
    result = _profile(request, nurse, NurseForm)
    if not isinstance(result, tuple):
        return result
    form, can_edit = result
    return render(
        request,
        "doctors/detail.html",
        {"p": nurse, "kind": "nurse", "form": form, "apps": None, "can_edit": can_edit, "council": "Nursing Council", "page_title": str(nurse)},
    )


@role_required(*EDIT_ROLES)
def nurse_add(request):
    """Add a nurse by NCJ number; the Nursing Council register is checked straight away."""
    form = AddNurseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        number = services.clean_mcj(data.pop("ncj_number"))
        if Nurse.objects.filter(ncj_number=number).exists():
            messages.info(request, f"NCJ {number} is already in the register.")
            return redirect("doctors:nurse-detail", ncj=number)
        nurse = services.add_nurse(number, user=request.user, **data)
        if nurse.status == "confirmed":
            messages.success(request, f"{nurse} confirmed from the Nursing Council register.")
        else:
            messages.warning(
                request,
                f"NCJ {number} could not be confirmed from the register ({nurse.get_register_status_display()}); it is waiting in the confirmation queue.",
            )
        return redirect("doctors:nurse-detail", ncj=nurse.ncj_number)
    return render(request, "doctors/nurse_add.html", {"form": form, "page_title": "Add a nurse"})


def _practitioner(kind, number):
    if kind not in ("doctor", "nurse"):
        raise Http404
    if kind == "doctor":
        return get_object_or_404(Doctor, mcj_number=number)
    return get_object_or_404(Nurse, ncj_number=number)


@require_POST
@role_required(*EDIT_ROLES)
def check_register(request, kind, number):
    """Check one practitioner against the council register now."""
    p = _practitioner(kind, number)
    outcome = verify(p, user=request.user)
    text = {
        "confirmed": f"Confirmed from the council register: {p.get_register_status_display()}.",
        "still_pending": f"Register says: {p.get_register_status_display()}. Left in the confirmation queue for a decision.",
        "ok": f"Register says: {p.get_register_status_display()}.",
        "concern": f"Register says: {p.get_register_status_display()}. Council confirmers have been told.",
        "unavailable": "The council register could not be reached. Try again later.",
    }[outcome]
    (messages.success if outcome in ("confirmed", "ok") else messages.warning)(request, text)
    return redirect(practitioner_link(p))


@require_POST
@role_required(*EDIT_ROLES)
def upload_photo(request, kind, number):
    """Profile photo for a doctor or nurse."""
    p = _practitioner(kind, number)
    try:
        p.photo = images.replace(p.photo, request.FILES.get("photo"), "practitioner_photo", user=request.user)
    except images.ImageRejected as exc:
        messages.error(request, str(exc))
        return redirect(practitioner_link(p))
    p.save(update_fields=["photo", "updated_at"])
    audit.record(f"{kind}.photo_updated", p, f"Photo of {p} updated")
    messages.success(request, "Photo saved.")
    return redirect(practitioner_link(p))


@role_required("manager", "mcj_confirmer", "supervisor")
def confirmations(request):
    """DV10003: doctors and nurses the council register could not confirm, waiting for a person to check with the council."""
    pending = Doctor.objects.filter(status="pending").order_by("created_at")
    rows = [{"d": d, "apps": Application.objects.filter(doctor=d, status__in=Application.OPEN_STATUSES)} for d in pending]
    return render(
        request,
        "doctors/confirmations.html",
        {
            "rows": rows,
            "nurses": Nurse.objects.filter(status="pending").order_by("created_at"),
            "can_decide": has_role(request.user, *DECIDE_ROLES),
            "registers": registers.register_summary(),
            "concerns": Doctor.objects.filter(status="confirmed", register_status__in=["lapsed", "suspended", "removed", "not_found"]).count()
            + Nurse.objects.filter(status="confirmed", register_status__in=["lapsed", "suspended", "removed", "not_found"]).count(),
            "page_title": "Council confirmations",
        },
    )


@require_POST
@role_required(*DECIDE_ROLES)
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


@require_POST
@role_required(*DECIDE_ROLES)
def decide_nurse(request, ncj):
    """Record the Nursing Council's answer."""
    nurse = get_object_or_404(Nurse, ncj_number=ncj, status="pending")
    note = request.POST.get("note", "").strip()
    if request.POST.get("decision") == "confirm":
        services.confirm_nurse(nurse, user=request.user, note=note)
        messages.success(request, f"NCJ {ncj} confirmed.")
    else:
        if not note:
            messages.error(request, "Record what the Nursing Council said.")
            return redirect("doctors:confirmations")
        services.reject_nurse(nurse, user=request.user, note=note)
        messages.success(request, f"NCJ {ncj} not confirmed.")
    return redirect("doctors:confirmations")


IMPORT_COLUMNS = ["registration_number", "title", "first_name", "last_name", "specialty", "status", "valid_until"]


def parse_register_csv(text):
    """Rows from a council extract (CSV with a header row). Returns (rows, errors)."""
    from .registers import _parse_date, normalise_status

    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower().replace(" ", "_"): h for h in (reader.fieldnames or [])}
    number_col = next((headers[h] for h in ("registration_number", "number", "reg_no", "registration_no") if h in headers), None)
    if number_col is None:
        return [], ["The file needs a registration_number column (see the column list on this page)."]

    def col(row, *names):
        for n in names:
            if n in headers:
                return (row.get(headers[n]) or "").strip()
        return ""

    rows, errors = [], []
    for i, row in enumerate(reader, start=2):
        number = services.clean_mcj(row.get(number_col))
        if not number:
            errors.append(f"Line {i}: no registration number")
            continue
        expiry_raw = col(row, "valid_until", "expiry", "expiry_date")
        expiry = _parse_date(expiry_raw)
        if expiry_raw and expiry is None:
            errors.append(f"Line {i}: date '{expiry_raw}' is not YYYY-MM-DD")
        rows.append(
            {
                "number": number,
                "title": col(row, "title")[:10],
                "first_name": col(row, "first_name", "given_name")[:60],
                "last_name": col(row, "last_name", "surname")[:60],
                "specialty": col(row, "specialty", "category")[:80],
                "status": normalise_status(col(row, "status") or "active"),
                "valid_until": expiry,
            }
        )
    return rows, errors


@role_required("manager", "mcj_confirmer", "back_office")
def register_import(request):
    """Load the extract a council supplies into the local copy of its register (replaces earlier rows for the same numbers)."""
    preview = None
    if request.method == "POST":
        council = request.POST.get("council")
        upload = request.FILES.get("file")
        if council not in dict(COUNCILS) or upload is None:
            messages.error(request, "Choose the council and the file.")
            return redirect("doctors:register-import")
        if upload.size > 20 * 1024 * 1024:
            messages.error(request, "The file is larger than 20 MB.")
            return redirect("doctors:register-import")
        text = upload.read().decode("utf-8-sig", errors="replace")
        rows, errors = parse_register_csv(text)
        if request.POST.get("confirm") and rows and not errors:
            created = updated = 0
            for r in rows:
                number = r.pop("number")
                _, was_created = CouncilRegisterEntry.objects.update_or_create(council=council, number=number, defaults={**r, "source": "file"})
                created += was_created
                updated += not was_created
            IntegrationRun.objects.create(
                system=council, operation="import", adapter="file", ok=True, reference=upload.name[:80], message=f"{created} new, {updated} updated"
            )
            audit.record(
                "register.imported", None, f"{dict(COUNCILS)[council]} register extract {upload.name}: {created} new, {updated} updated", council=council
            )
            messages.success(
                request, f"{dict(COUNCILS)[council]} register: {created} new and {updated} updated entries. Pending practitioners can now be re-checked."
            )
            return redirect("doctors:register-import")
        preview = {"council": council, "rows": rows[:15], "count": len(rows), "errors": errors[:20], "error_count": len(errors), "name": upload.name}
    return render(
        request,
        "doctors/register_import.html",
        {
            "councils": COUNCILS,
            "columns": IMPORT_COLUMNS,
            "preview": preview,
            "registers": registers.register_summary(),
            "page_title": "Council register import",
        },
    )
