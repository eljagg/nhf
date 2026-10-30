from django import forms
from django.contrib import admin

from apps.accounts.roles import has_role

from . import audit
from .models import PARAMETER_LIMITS, SECURITY_PARAMETERS, AuditEvent, Centre, IntegrationRun, Notification, Parameter


class ParameterForm(forms.ModelForm):
    class Meta:
        model = Parameter
        fields = ["value", "description"]

    def clean_value(self):
        value = self.cleaned_data["value"]
        key = self.instance.key
        if key in PARAMETER_LIMITS:
            low, high = PARAMETER_LIMITS[key]
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError("Enter a whole number.") from exc
            if not low <= number <= high:
                raise forms.ValidationError(f"Must be between {low} and {high} — this is a security control.")
            return number
        return value


@admin.register(Centre)
class CentreAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "parish", "prints_cards", "is_active")


@admin.register(Parameter)
class ParameterAdmin(admin.ModelAdmin):
    """Parameters are seeded; they are edited, never added or deleted. Security parameters: application administrators and the DPO only."""

    form = ParameterForm
    list_display = ("key", "value", "description", "updated_at")
    readonly_fields = ("key",)
    fields = ("key", "value", "description")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.key in SECURITY_PARAMETERS and not (request.user.is_superuser or has_role(request.user, "ict_admin", "dpo")):
            return False
        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        old = Parameter.objects.filter(pk=obj.pk).values_list("value", flat=True).first() if change else None
        super().save_model(request, obj, form, change)
        audit.record(
            "config.parameter_changed",
            obj,
            f"Parameter {obj.key} changed from {old!r} to {obj.value!r} by {request.user.username}",
            key=obj.key,
            old=old,
            new=obj.value,
        )


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
