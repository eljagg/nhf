"""Create the first administrator from ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL if set (idempotent)."""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create the bootstrap administrator account from environment variables."

    def handle(self, *args, **opts):
        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
        if not username or not password:
            self.stdout.write("admin: ADMIN_USERNAME/ADMIN_PASSWORD not set; skipped")
            return
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username, defaults={"email": os.environ.get("ADMIN_EMAIL", ""), "is_staff": True, "is_superuser": True}
        )
        if created:
            user.set_password(password)
            user.save()
        user.groups.add(*Group.objects.filter(name="ict_admin"))
        self.stdout.write(f"admin: {username} {'created' if created else 'present'}")
