"""Back-office user administration, hardened for separation of duties.

* Nobody edits their own account here (roles, flags, password): ask another administrator.
* Superuser status and individual permissions can only be changed by a superuser.
* E-mail and password of accounts holding a privileged role (manager, application/database administrator, DPO)
  can only be changed by a superuser: otherwise an administrator could redirect the reset e-mail and take the account over.
* Roles (groups) of local accounts change only through a request on the Staff page approved by a manager
  (two people); directory accounts take their roles from AD / Entra groups.
* Every change of roles, flags, lock or password is written to the audit trail.
"""

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied

from apps.core import audit

from .models import TemporaryRole, User
from .roles import role_names

PROTECTED_FLAGS = ("is_superuser", "user_permissions", "groups")  # roles: request + manager approval on the Staff page


def is_privileged(user):
    return bool(user and (user.is_superuser or role_names(user) & set(settings.MFA_REQUIRED_ROLES)))


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        *BaseUserAdmin.fieldsets,
        ("NHF", {"fields": ("centre", "staff_number", "job_title", "phone", "source", "locked_until", "lock_reason")}),
        ("Suspension (managed on the Staff page)", {"fields": ("suspended_at", "suspended_until", "suspension_reason", "suspended_by")}),
    )
    list_display = ("username", "first_name", "last_name", "centre", "source", "is_active", "suspended_at", "locked_until")
    list_filter = ("is_active", "source", "groups", "centre")

    def get_readonly_fields(self, request, obj=None):
        ro = ["suspended_at", "suspended_until", "suspension_reason", "suspended_by", "source", "last_login", "date_joined"]
        if not request.user.is_superuser:
            ro += list(PROTECTED_FLAGS)
            if obj is not None and is_privileged(obj):
                ro.append("email")
        return ro

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.pk == request.user.pk and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and super().has_delete_permission(request, obj)

    def user_change_password(self, request, id, form_url=""):
        target = self.get_object(request, id)
        if target is not None and not request.user.is_superuser and (target.pk == request.user.pk or is_privileged(target)):
            raise PermissionDenied("Only a superuser can set the password of a privileged account.")
        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and getattr(response, "status_code", 200) == 302 and target is not None:
            audit.record("security.password_set_by_admin", target, f"Password of {target.username} set by {request.user.username} in the back office")
        return response

    def save_model(self, request, obj, form, change):
        before = User.objects.filter(pk=obj.pk).first() if change else None
        super().save_model(request, obj, form, change)
        if before is not None:
            fields = [f for f in ("is_active", "is_staff", "is_superuser", "email", "locked_until", "centre_id") if getattr(before, f) != getattr(obj, f)]
            if fields:
                audit.record(
                    "security.user_changed", obj, f"{obj.username} changed in the back office by {request.user.username}: {', '.join(fields)}", fields=fields
                )
            if obj.is_temporarily_locked and before.locked_until != obj.locked_until:
                from apps.security.services import end_sessions

                end_sessions(obj, by=request.user, reason="account locked by administrator")

    def save_related(self, request, form, formsets, change):
        obj = form.instance
        before = set(obj.groups.values_list("name", flat=True)) if change else set()
        super().save_related(request, form, formsets, change)
        after = set(obj.groups.values_list("name", flat=True))
        if before != after:
            audit.record(
                "security.roles_changed",
                obj,
                f"Roles of {obj.username} changed by {request.user.username}: added {sorted(after - before) or 'none'}, removed {sorted(before - after) or 'none'}",
                added=sorted(after - before),
                removed=sorted(before - after),
            )


@admin.register(TemporaryRole)
class TemporaryRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "starts_at", "expires_at", "revoked_at", "granted_by")

    def has_add_permission(self, request):
        return request.user.is_superuser  # grants go through the Temporary roles screen, which enforces who may grant what

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser
