"""Sign-in, MFA, temporary roles and account locks."""

import base64
import io
from datetime import timedelta

import qrcode
import qrcode.image.svg
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group
from django.contrib.auth.views import PasswordChangeView, PasswordResetConfirmView, PasswordResetView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core import audit

from .models import TemporaryRole
from .roles import ROLES, role_names, role_required


class LoginForm(AuthenticationForm):
    """Standard sign-in with the administrator temporary lock honoured."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_suspended:
            raise forms.ValidationError("This account is suspended. Contact your manager or the application administrator.", code="suspended")
        if user.is_temporarily_locked:
            raise forms.ValidationError("This account is temporarily locked. Contact the application administrator.", code="locked")


def _safe_next(request, default="core:home"):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return nxt
    return default


def login_view(request):
    """Sign in (UM10001). Local accounts, or Active Directory over LDAPS through ActiveDirectoryBackend (UM10005); Entra ID has its own button (UM10006)."""
    form = LoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        audit.record("auth.login", user, f"{user.username} signed in", actor=user)
        return redirect(_safe_next(request))
    if request.method == "POST":
        audit.record("auth.login_failed", None, f"Failed sign-in for {request.POST.get('username', '')[:60]}")
    from django.conf import settings

    return render(
        request,
        "accounts/login.html",
        {
            "form": form,
            "idle": request.GET.get("idle"),
            "suspended": request.GET.get("suspended"),
            "directory_error": getattr(request, "directory_error", ""),
            "ldap_enabled": settings.LDAP["ENABLED"],
            "oidc_enabled": settings.OIDC["ENABLED"],
            "oidc_label": settings.OIDC["BUTTON_LABEL"],
        },
    )


@require_POST
def logout_view(request):
    """Sign out."""
    if request.user.is_authenticated:
        audit.record("auth.logout", request.user, f"{request.user.username} signed out")
    logout(request)
    return redirect("accounts:login")


def _qr_svg(uri):
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


@login_required
def mfa_setup(request):
    """Enrol a TOTP authenticator (Microsoft/Google Authenticator) (UM10004)."""
    device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first() or TOTPDevice.objects.create(
        user=request.user, name="Authenticator", confirmed=False
    )
    error = ""
    if request.method == "POST":
        if device.verify_token(request.POST.get("token", "").strip()):
            device.confirmed = True
            device.save()
            TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
            otp_login(request, device)
            audit.record("auth.mfa_enrolled", request.user, "TOTP device enrolled")
            request.session["new_backup_codes"] = issue_backup_codes(request.user)
            request.session["after_backup_codes"] = _safe_next(request)
            messages.success(request, "Authenticator enrolled. You will be asked for a code at each sign-in.")
            return redirect("accounts:mfa-backup-codes")
        error = "That code did not match. Check the time on your phone and try the current code."
    return render(request, "accounts/mfa_setup.html", {"qr": _qr_svg(device.config_url), "secret": base64.b32encode(device.bin_key).decode(), "error": error})


@login_required
def mfa_verify(request):
    """Second factor at sign-in."""
    error = ""
    if request.method == "POST":
        token = request.POST.get("token", "").replace(" ", "").strip()
        devices = list(TOTPDevice.objects.filter(user=request.user, confirmed=True)) + list(StaticDevice.objects.filter(user=request.user, confirmed=True))
        for device in devices:
            if device.verify_token(token):
                otp_login(request, device)
                kind = "backup code" if isinstance(device, StaticDevice) else "authenticator code"
                audit.record("auth.mfa_verified", request.user, f"MFA verified with {kind}")
                if isinstance(device, StaticDevice):
                    left = device.token_set.count()
                    messages.warning(request, f"Backup code used. {left} left — generate new ones from My account if you are running low.")
                return redirect(_safe_next(request))
        error = "Code not accepted."
        audit.record("auth.mfa_failed", request.user, "MFA code rejected")
        _count_mfa_failure(request.user)
    return render(request, "accounts/mfa_verify.html", {"error": error, "next": request.GET.get("next", "")})


def issue_backup_codes(user, count=10):
    """Replace the user's backup codes with ten new single-use codes; returns them for one-time display."""
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name="Backup codes", confirmed=True)
    codes = []
    for _ in range(count):
        code = StaticToken.random_token()
        device.token_set.create(token=code)
        codes.append(code)
    audit.record("auth.backup_codes_issued", user, f"{count} backup codes issued", actor=user)
    return codes


def _count_mfa_failure(user):
    from django.core.cache import cache

    from apps.core.models import Parameter
    from apps.security.services import raise_alert

    key = f"mfa-fail:{user.pk}"
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 15 * 60)
        n = 1
    if n >= int(Parameter.get("alert-failed-mfa")):
        raise_alert(
            "failed_mfa",
            f"{n} wrong two-step codes for {user.username} within 15 minutes — password may be known to someone else.",
            severity="high",
            user=user,
            dedupe_minutes=15,
        )


@login_required
def mfa_backup_codes(request):
    """Show newly issued backup codes once."""
    codes = request.session.pop("new_backup_codes", None)
    if not codes:
        return redirect("accounts:me")
    return render(request, "accounts/mfa_backup_codes.html", {"codes": codes, "next": request.session.pop("after_backup_codes", "/")})


@require_POST
@login_required
def regenerate_backup_codes(request):
    """New set of backup codes (old ones stop working)."""
    request.session["new_backup_codes"] = issue_backup_codes(request.user)
    request.session["after_backup_codes"] = reverse("accounts:me")
    return redirect("accounts:mfa-backup-codes")


class TemporaryRoleForm(forms.Form):
    """Grant a role for a set number of hours."""

    user = forms.ModelChoiceField(queryset=None)
    role = forms.ChoiceField(choices=[(k, v[0]) for k, v in ROLES.items()])
    hours = forms.IntegerField(min_value=1, max_value=24 * 30, initial=8)
    reason = forms.CharField(max_length=200)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = get_user_model().objects.filter(is_active=True).order_by("username")


@role_required("manager", "ict_admin")
def temporary_roles(request):
    """Grant and revoke temporary roles (UM10007)."""
    form = TemporaryRoleForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = Group.objects.get(name=form.cleaned_data["role"])
        grant = TemporaryRole.objects.create(
            user=form.cleaned_data["user"],
            group=group,
            expires_at=timezone.now() + timedelta(hours=form.cleaned_data["hours"]),
            reason=form.cleaned_data["reason"],
            granted_by=request.user,
        )
        audit.record(
            "role.temporary_granted",
            grant.user,
            f"{ROLES[group.name][0]} granted to {grant.user} until {timezone.localtime(grant.expires_at):%d %b %H:%M}",
            role=group.name,
        )
        messages.success(request, f"{ROLES[group.name][0]} granted to {grant.user.display_name()} until {timezone.localtime(grant.expires_at):%d %b %Y %H:%M}.")
        return redirect("accounts:temporary-roles")
    grants = TemporaryRole.objects.select_related("user", "group", "granted_by")[:100]
    return render(request, "accounts/temporary_roles.html", {"form": form, "grants": grants, "roles": ROLES})


@require_POST
@role_required("manager", "ict_admin")
def revoke_temporary_role(request, pk):
    """Revoke a grant before it expires."""
    grant = get_object_or_404(TemporaryRole, pk=pk, revoked_at__isnull=True)
    grant.revoked_at = timezone.now()
    grant.save(update_fields=["revoked_at"])
    audit.record("role.temporary_revoked", grant.user, f"{grant.group.name} revoked from {grant.user}")
    messages.success(request, "Grant revoked.")
    return redirect("accounts:temporary-roles")


@login_required
def my_account(request):
    """Who am I, what can I do, where am I signed in."""
    from apps.security.services import active_sessions

    return render(
        request,
        "accounts/me.html",
        {
            "roles": sorted(role_names(request.user)),
            "catalogue": ROLES,
            "temp": request.user.temporary_roles.select_related("group")[:10],
            "sessions": active_sessions(request.user),
            "current_key": request.session.session_key,
            "backup_left": sum(d.token_set.count() for d in StaticDevice.objects.filter(user=request.user)),
        },
    )


@require_POST
@login_required
def end_other_sessions(request):
    """Sign out of every other browser or device."""
    from apps.security.services import end_sessions

    count = end_sessions(request.user, by=request.user, reason="signed out by the user from another session", keep_key=request.session.session_key)
    messages.success(request, f"Signed out of {count} other session(s).")
    return redirect("accounts:me")


class StaffPasswordChangeView(PasswordChangeView):
    """Change password (also where expired passwords are sent)."""

    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:me")

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.record("auth.password_changed", self.request.user, f"{self.request.user.username} changed their password")
        messages.success(self.request, "Password changed.")
        return response


class ThrottledPasswordResetView(PasswordResetView):
    """Self-service reset by e-mail; at most five requests an hour from one address. The response never reveals whether the e-mail exists."""

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.txt"
    subject_template_name = "accounts/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password-reset-done")

    def form_valid(self, form):
        from django.core.cache import cache

        from apps.security.signals import client_ip

        key = f"pwreset:{client_ip(self.request)}"
        count = cache.get(key, 0)
        if count >= 5:
            return redirect(self.success_url)
        cache.set(key, count + 1, 3600)
        audit.record("auth.password_reset_requested", None, f"Password reset requested for {form.cleaned_data.get('email', '')[:80]}")
        return super().form_valid(form)


class AuditedPasswordResetConfirmView(PasswordResetConfirmView):
    """Set the new password from the e-mailed link."""

    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password-reset-complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.record("auth.password_reset", form.user, f"{form.user.username} reset their password by e-mail link", actor=form.user)
        return response
