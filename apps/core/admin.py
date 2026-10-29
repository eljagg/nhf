from django.contrib import admin

from .models import AuditEvent, Centre, IntegrationRun, Notification, Parameter


@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "parish", "prints_cards", "is_active")


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description", "updated_at")


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("at", "actor", "action", "object_type", "object_id", "summary")
    list_filter = ("action",)
    search_fields = ("summary", "object_id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "channel", "to", "template", "status")
    list_filter = ("channel", "status", "template")


@admin.register(IntegrationRun)
class IntegrationRunAdmin(admin.ModelAdmin):
    list_display = ("at", "system", "operation", "adapter", "ok", "duration_ms", "reference")
    list_filter = ("system", "ok")
