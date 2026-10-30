from django.contrib import admin

from .models import AccessLog, SecurityAlert, UserSession


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ("at", "user", "method", "path", "status", "duration_ms", "ip_address")
    list_filter = ("method", "status")
    search_fields = ("path", "user__username", "object_ref")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "last_seen", "ip_address", "ended_at", "end_reason")
    exclude = ("session_key",)


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = ("at", "kind", "severity", "subject", "message", "acknowledged_at")
    list_filter = ("kind", "severity")
