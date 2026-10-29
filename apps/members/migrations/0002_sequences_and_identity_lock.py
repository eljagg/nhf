"""Member-number and tracking sequences; database-level lock on protected identity fields (BR10001–BR10003)."""
from django.db import migrations

FORWARD = r"""
CREATE SEQUENCE IF NOT EXISTS members_member_number_seq START 2000000001;
CREATE SEQUENCE IF NOT EXISTS members_tracking_seq START 1;

CREATE OR REPLACE FUNCTION members_protect_identity() RETURNS trigger AS $$
BEGIN
  IF (NEW.first_name IS DISTINCT FROM OLD.first_name
      OR NEW.middle_name IS DISTINCT FROM OLD.middle_name
      OR NEW.last_name IS DISTINCT FROM OLD.last_name
      OR NEW.dob IS DISTINCT FROM OLD.dob
      OR NEW.gender IS DISTINCT FROM OLD.gender
      OR NEW.trn IS DISTINCT FROM OLD.trn)
     AND coalesce(current_setting('nhf.identity_write', true), 'off') <> 'on' THEN
    RAISE EXCEPTION 'Protected identity fields (name, date of birth, gender, TRN) can only be changed through the TRN Validator'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS members_protect_identity ON members_member;
CREATE TRIGGER members_protect_identity BEFORE UPDATE ON members_member
  FOR EACH ROW EXECUTE FUNCTION members_protect_identity();
"""

REVERSE = r"""
DROP TRIGGER IF EXISTS members_protect_identity ON members_member;
DROP FUNCTION IF EXISTS members_protect_identity();
DROP SEQUENCE IF EXISTS members_tracking_seq;
DROP SEQUENCE IF EXISTS members_member_number_seq;
"""


class Migration(migrations.Migration):
    dependencies = [("members", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
