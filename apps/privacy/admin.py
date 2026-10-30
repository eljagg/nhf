from django.contrib import admin

from apps.rules.admin import AuditedAdmin

from .models import Breach, DataSubjectRequest, ProcessingActivity, RetentionRun


@admin.register(ProcessingActivity)
class ProcessingActivityAdmin(AuditedAdmin):
    list_display = ("name", "lawful_basis", "sensitive", "retention", "updated_at")


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(admin.ModelAdmin):
    list_display = ("reference", "kind", "requester_name", "status", "due_at")
    readonly_fields = ("reference",)


@admin.register(Breach)
class BreachAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "severity", "status", "discovered_at")
    readonly_fields = ("reference",)


@admin.register(RetentionRun)
class RetentionRunAdmin(admin.ModelAdmin):
    list_display = ("at", "dry_run", "results", "run_by")
