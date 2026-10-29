from django.contrib import admin

from .models import SrnIssue, TajIdentity, TrnValidation


@admin.register(TrnValidation)
class TrnValidationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "trn", "purpose", "status", "match_result", "adapter", "duration_ms")
    list_filter = ("status", "match_result", "purpose")
    search_fields = ("trn",)
    exclude = ("payload", "form_identity")


@admin.register(SrnIssue)
class SrnIssueAdmin(admin.ModelAdmin):
    list_display = ("created_at", "first_name", "last_name", "dob", "status", "srn", "decided_by")
    list_filter = ("status",)


@admin.register(TajIdentity)
class TajIdentityAdmin(admin.ModelAdmin):
    list_display = ("trn", "first_name", "last_name", "dob", "gender", "demo_note")
    search_fields = ("trn", "last_name", "demo_note")
