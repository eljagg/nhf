from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("privacy", "0001_initial")]
    operations = [
        migrations.RunSQL(
            "CREATE SEQUENCE IF NOT EXISTS privacy_dsr_seq START 1; CREATE SEQUENCE IF NOT EXISTS privacy_breach_seq START 1;",
            "DROP SEQUENCE IF EXISTS privacy_dsr_seq; DROP SEQUENCE IF EXISTS privacy_breach_seq;",
        )
    ]
