from django.contrib import admin

from .models import ReportSchedule, SavedReport


@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "owner", "shared", "updated_at")
    list_filter = ("kind", "shared")
    search_fields = ("name",)
    readonly_fields = ("definition", "owner", "created_at", "updated_at")


@admin.register(ReportSchedule)
class ReportScheduleAdmin(admin.ModelAdmin):
    list_display = ("report", "frequency", "hour", "active", "next_run_at", "last_run_at", "last_result")
    list_filter = ("frequency", "active")
