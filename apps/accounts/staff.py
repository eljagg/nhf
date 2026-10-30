"""Staff directory: profile photo, ID picture and number, suspension (UM10002, UM10011)."""

from datetime import datetime, time

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from apps.core import audit, images
from apps.core.notifications import notify_role

from .roles import ROLES, has_role, role_names, role_required, users_with_role

VIEW_ROLES = ("ict_admin", "manager", "auditor")
EDIT_ROLES = ("ict_admin", "manager")


class StaffForm(forms.ModelForm):
    """Details an administrator or manager keeps on a staff member."""

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email", "job_title", "phone", "staff_number", "centre", "id_type", "id_number", "id_expiry"]
        widgets = {"id_expiry": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault("class", "inp")
        self.fields["id_number"].widget = forms.TextInput(attrs={"class": "inp font-mono", "autocomplete": "off"})
        if self.instance.source != "local":
            for name in ("first_name", "last_name", "email"):
                self.fields[name].disabled = True
                self.fields[name].help_text = "Comes from the directory."

    def clean_id_number(self):
        value = " ".join(self.cleaned_data.get("id_number", "").split()).upper()
        if value and not self.cleaned_data.get("id_type") and not self.data.get("id_type"):
            raise forms.ValidationError("Choose the ID type.")
        return value


def _status(u):
    if u.is_suspended:
        return "suspended"
    if not u.is_active:
        return "disabled"
    if u.is_temporarily_locked:
        return "locked"
    return "active"


@role_required(*VIEW_ROLES)
def staff_list(request):
    """Everyone with an account."""
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "")
    qs = get_user_model().objects.select_related("centre").prefetch_related("groups").order_by("last_name", "first_name", "username")
    if q:
        qs = qs.filter(
            Q(username__icontains=q) | Q(first_name__istartswith=q) | Q(last_name__istartswith=q) | Q(staff_number__iexact=q) | Q(email__istartswith=q)
        )
    now = timezone.now()
    if state == "suspended":
        qs = qs.filter(suspended_at__isnull=False).filter(Q(suspended_until__isnull=True) | Q(suspended_until__gt=now))
    elif state == "disabled":
        qs = qs.filter(is_active=False)
    elif state == "no_id":
        qs = qs.filter(Q(id_number="") | Q(id_document__isnull=True), is_active=True)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    rows = [{"u": u, "status": _status(u), "roles": [ROLES.get(g.name, (g.name,))[0] for g in u.groups.all()]} for u in page]
    return render(request, "accounts/staff_list.html", {"page": page, "rows": rows, "q": q, "state": state, "page_title": "Staff"})


@role_required(*VIEW_ROLES)
def staff_detail(request, user_id):
    """Profile; administrators and managers edit details, photo and ID, and suspend or reinstate."""
    target = get_object_or_404(get_user_model(), pk=user_id)
    can_edit = has_role(request.user, *EDIT_ROLES)
    form = StaffForm(request.POST or None, instance=target)
    if request.method == "POST":
        if not can_edit:
            return redirect("accounts:staff-detail", user_id=target.pk)
        if form.is_valid():
            form.save()
            audit.record("staff.updated", target, f"Staff record of {target.username} updated", fields=list(form.changed_data))
            messages.success(request, "Staff details saved.")
            return redirect("accounts:staff-detail", user_id=target.pk)
    if not can_edit:
        for f in form.fields.values():
            f.disabled = True
        form.initial["id_number"] = target.id_number_masked
    return render(
        request,
        "accounts/staff_detail.html",
        {
            "t": target,
            "form": form,
            "status": _status(target),
            "can_edit": can_edit,
            "can_suspend": can_edit and target.pk != request.user.pk,
            "can_see_id": has_role(request.user, *images.VIEW_ROLES["staff_id"]),
            "roles": sorted(ROLES.get(r, (r,))[0] for r in role_names(target)),
            "page_title": target.display_name(),
        },
    )


@require_POST
@role_required(*EDIT_ROLES)
def staff_image(request, user_id, kind):
    """Upload or replace a staff photo or ID picture."""
    target = get_object_or_404(get_user_model(), pk=user_id)
    spec = {"photo": ("photo", "staff_photo", "Profile photo"), "id": ("id_document", "staff_id", "ID picture")}.get(kind)
    if spec is None:
        raise Http404
    field, image_kind, label = spec
    try:
        setattr(target, field, images.replace(getattr(target, field), request.FILES.get("image"), image_kind, user=request.user))
    except images.ImageRejected as exc:
        messages.error(request, str(exc))
        return redirect("accounts:staff-detail", user_id=target.pk)
    target.save(update_fields=[field])
    audit.record(f"staff.{field}_updated", target, f"{label} of {target.username} updated by {request.user.username}")
    messages.success(request, f"{label} saved.")
    return redirect("accounts:staff-detail", user_id=target.pk)


def _last_admin(target):
    """True if suspending this person would leave no usable application administrator."""
    if "ict_admin" not in role_names(target):
        return False
    others = [u for u in users_with_role("ict_admin") if u.pk != target.pk and not u.is_suspended]
    return not others


@require_POST
@role_required(*EDIT_ROLES)
def suspend(request, user_id):
    """Suspend an account: sign-in refused and every session ended at once. Never your own."""
    from apps.security.services import end_sessions

    target = get_object_or_404(get_user_model(), pk=user_id)
    reason = request.POST.get("reason", "").strip()[:300]
    until = parse_date(request.POST.get("until", "") or "")
    if target.pk == request.user.pk:
        messages.error(request, "You cannot suspend your own account.")
    elif not reason:
        messages.error(request, "Give the reason for the suspension.")
    elif until and until <= timezone.localdate():
        messages.error(request, "The end date must be in the future.")
    elif _last_admin(target):
        messages.error(request, "This is the only active application administrator. Give the role to someone else first.")
    else:
        target.suspended_at = timezone.now()
        target.suspended_until = timezone.make_aware(datetime.combine(until, time.min)) if until else None
        target.suspension_reason = reason
        target.suspended_by = request.user
        target.save(update_fields=["suspended_at", "suspended_until", "suspension_reason", "suspended_by"])
        ended = end_sessions(target, by=request.user, reason="account suspended")
        audit.record(
            "staff.suspended",
            target,
            f"{target.username} suspended by {request.user.username}{' until ' + until.isoformat() if until else ''}: {reason}",
            until=until.isoformat() if until else None,
        )
        notify_role(
            "manager",
            "staff-suspended",
            obj=target,
            link=f"/accounts/staff/{target.pk}/",
            who=target.display_name(),
            by=request.user.display_name(),
            reason=reason,
        )
        messages.success(request, f"{target.display_name()} is suspended and was signed out of {ended} session(s).")
    return redirect("accounts:staff-detail", user_id=target.pk)


@require_POST
@role_required(*EDIT_ROLES)
def reinstate(request, user_id):
    """Lift a suspension."""
    target = get_object_or_404(get_user_model(), pk=user_id)
    if target.pk == request.user.pk:
        messages.error(request, "Ask another administrator or manager to reinstate your account.")
        return redirect("accounts:staff-detail", user_id=target.pk)
    note = request.POST.get("note", "").strip()[:200]
    previous = target.suspension_reason
    target.suspended_at = target.suspended_until = None
    target.suspension_reason = ""
    target.suspended_by = None
    target.save(update_fields=["suspended_at", "suspended_until", "suspension_reason", "suspended_by"])
    audit.record("staff.reinstated", target, f"{target.username} reinstated by {request.user.username}: {note or 'no note'}", previous_reason=previous)
    messages.success(request, f"{target.display_name()} is reinstated and can sign in again.")
    return redirect("accounts:staff-detail", user_id=target.pk)


@require_POST
def my_photo(request):
    """Staff may set their own profile photo (not their ID)."""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    try:
        request.user.photo = images.replace(request.user.photo, request.FILES.get("image"), "staff_photo", user=request.user)
    except images.ImageRejected as exc:
        messages.error(request, str(exc))
        return redirect("accounts:me")
    request.user.save(update_fields=["photo"])
    audit.record("staff.photo_updated", request.user, f"{request.user.username} updated their profile photo")
    messages.success(request, "Profile photo saved.")
    return redirect("accounts:me")
