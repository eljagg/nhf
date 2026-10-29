from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import TemporaryRole, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (*BaseUserAdmin.fieldsets, ("NHF", {"fields": ("centre", "staff_number", "locked_until", "lock_reason")}))
    list_display = ("username", "first_name", "last_name", "centre", "is_active", "locked_until")
    list_filter = ("is_active", "groups", "centre")


@admin.register(TemporaryRole)
class TemporaryRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "starts_at", "expires_at", "revoked_at", "granted_by")
