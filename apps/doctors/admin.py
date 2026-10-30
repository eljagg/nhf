from django.contrib import admin

from .models import CouncilRegisterEntry, Doctor, Nurse


@admin.register(Doctor)
class DoctorAdmin(admin.ModelAdmin):
    list_display = ("mcj_number", "last_name", "first_name", "specialty", "town", "parish", "status", "register_status")
    list_filter = ("status", "register_status", "parish")
    search_fields = ("mcj_number", "last_name", "first_name", "practice_name", "town")
    raw_id_fields = ("photo",)


@admin.register(Nurse)
class NurseAdmin(admin.ModelAdmin):
    list_display = ("ncj_number", "last_name", "first_name", "category", "town", "parish", "status", "register_status")
    list_filter = ("status", "register_status", "category", "parish")
    search_fields = ("ncj_number", "last_name", "first_name", "practice_name", "town")
    raw_id_fields = ("photo",)


@admin.register(CouncilRegisterEntry)
class CouncilRegisterEntryAdmin(admin.ModelAdmin):
    list_display = ("council", "number", "last_name", "first_name", "specialty", "status", "valid_until", "source")
    list_filter = ("council", "status", "source")
    search_fields = ("number", "last_name", "first_name")
