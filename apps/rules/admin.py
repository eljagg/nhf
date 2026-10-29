"""Back-office configuration screens (BR10009–BR10011, US10002): programmes, benefits and conditions are added here without code."""

from django.contrib import admin

from apps.core import audit

from .models import Benefit, MedicalCondition, Programme, RejectionReason


class AuditedAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit.record(
            "config.changed" if change else "config.added",
            obj,
            f"{obj._meta.verbose_name} {obj} {'changed' if change else 'added'}",
            fields=list(form.changed_data),
        )


class BenefitInline(admin.TabularInline):
    model = Benefit
    extra = 0


@admin.register(Programme)
class ProgrammeAdmin(AuditedAdmin):
    list_display = ("name", "code", "min_age", "max_age", "auto_assign", "requires_condition", "is_active")
    inlines = [BenefitInline]


@admin.register(MedicalCondition)
class MedicalConditionAdmin(AuditedAdmin):
    list_display = ("name", "group", "sex_restriction", "min_age", "max_age", "is_active")
    list_filter = ("group", "sex_restriction", "programmes", "is_active")
    filter_horizontal = ("programmes",)
    search_fields = ("name", "code")


@admin.register(Benefit)
class BenefitAdmin(AuditedAdmin):
    list_display = ("name", "programme", "is_active")


@admin.register(RejectionReason)
class RejectionReasonAdmin(AuditedAdmin):
    list_display = ("label", "code", "is_system", "is_active")
