from django.contrib import admin

from .models import Card


@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ("member", "version_no", "reprint_seq", "reason", "state", "centre", "queued_at", "serial_number")
    list_filter = ("state", "reason", "centre")
    search_fields = ("member__member_number", "serial_number")
