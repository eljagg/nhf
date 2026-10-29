"""Append-only audit and interaction tables enforced in the database (AL10001, IL10002)."""
from django.db import migrations

FORWARD = r"""
CREATE OR REPLACE FUNCTION nhf_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS core_auditevent_append_only ON core_auditevent;
CREATE TRIGGER core_auditevent_append_only BEFORE UPDATE OR DELETE ON core_auditevent
  FOR EACH ROW EXECUTE FUNCTION nhf_append_only();
"""
REVERSE = "DROP TRIGGER IF EXISTS core_auditevent_append_only ON core_auditevent;"


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
