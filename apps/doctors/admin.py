from django.contrib import admin

from .models import Doctor


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("mcj_number", "last_name", "first_name", "specialty", "parish", "status")
    list_filter = ("status", "parish")
    search_fields = ("mcj_number", "last_name", "first_name")
