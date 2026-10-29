"""Interactions and notes cannot be changed or deleted, even outside the application (IL10002)."""
from django.db import migrations

FORWARD = r"""
DROP TRIGGER IF EXISTS interactions_append_only ON interactions_interaction;
CREATE TRIGGER interactions_append_only BEFORE UPDATE OR DELETE ON interactions_interaction
  FOR EACH ROW EXECUTE FUNCTION nhf_append_only();
DROP TRIGGER IF EXISTS interaction_notes_append_only ON interactions_interactionnote;
CREATE TRIGGER interaction_notes_append_only BEFORE UPDATE OR DELETE ON interactions_interactionnote
  FOR EACH ROW EXECUTE FUNCTION nhf_append_only();
"""
REVERSE = """
DROP TRIGGER IF EXISTS interactions_append_only ON interactions_interaction;
DROP TRIGGER IF EXISTS interaction_notes_append_only ON interactions_interactionnote;
"""


class Migration(migrations.Migration):
    dependencies = [("interactions", "0001_initial"), ("core", "0002_append_only")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
