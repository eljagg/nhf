from django.contrib import admin

from apps.rules.admin import AuditedAdmin

from .models import GroupMapping


@admin.register(GroupMapping)
class GroupMappingAdmin(AuditedAdmin):
    list_display = ("group", "source", "role", "centre", "note")
    list_filter = ("source", "role")
    search_fields = ("group",)
