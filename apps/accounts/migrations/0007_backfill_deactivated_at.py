from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """Accounts already disabled before v0.2.3 start their retention clock now."""
    apps.get_model("accounts", "User").objects.filter(is_active=False, deactivated_at__isnull=True).update(deactivated_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_user_deactivated_at")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
