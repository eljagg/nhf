"""Create the role groups and their back-office permissions (idempotent)."""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from apps.accounts.roles import ROLES

# Back-office (Django admin) permissions per role. Member records are never edited through the admin.
ADMIN_PERMS = {
    "back_office": [
        ("rules", None),
        ("core", "centre"),
        ("core", "parameter"),
        ("doctors", "doctor"),
        ("doctors", "nurse"),
        ("doctors", "councilregisterentry"),
    ],
    "ict_admin": [("accounts", "user"), ("accounts", "temporaryrole"), ("auth", "group"), ("directory", "groupmapping")],
    "dpo": [("privacy", None), ("core", "parameter")],
    "auditor": [("core", "auditevent"), ("core", "integrationrun"), ("core", "notification")],
}


class Command(BaseCommand):
    help = "Create one auth Group per platform role and grant back-office permissions."

    def handle(self, *args, **opts):
        for code in ROLES:
            group, _ = Group.objects.get_or_create(name=code)
            for app_label, model in ADMIN_PERMS.get(code, []):
                perms = Permission.objects.filter(content_type__app_label=app_label)
                if model:
                    perms = perms.filter(content_type__model=model)
                if code == "auditor":
                    perms = perms.filter(codename__startswith="view_")
                group.permissions.add(*perms)
        self.stdout.write(f"roles: {len(ROLES)} groups present")
