"""Re-encrypt every encrypted column with the current key (the first key in FIELD_ENCRYPTION_KEY).

Rotation: set FIELD_ENCRYPTION_KEY="NEW,OLD", deploy, run `python manage.py rotate_field_keys`, then drop OLD
(and set FIELD_ENCRYPTION_LEGACY_FALLBACK=0 once nothing uses the SECRET_KEY-derived key).

Works on the raw stored tokens in one transaction: if any token cannot be opened with the configured keys the
command stops, nothing is written, and it reports where. Append-only tables (audit trail, interaction log and notes)
cannot be rewritten by design; keep OLD in the list for as long as those rows are retained.
"""

from cryptography.fernet import InvalidToken
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.core.crypto import EncryptedJSONField, EncryptedTextField, rotate

APPEND_ONLY = {"core_auditevent", "interactions_interaction", "interactions_interactionnote"}


def _columns():
    from apps.core.models import StoredImage

    for model in apps.get_models():
        table = model._meta.db_table
        if table in APPEND_ONLY:
            continue
        for f in model._meta.fields:
            if isinstance(f, EncryptedJSONField | EncryptedTextField):
                yield table, model._meta.pk.column, f.column
    yield StoredImage._meta.db_table, "id", "data"


class Command(BaseCommand):
    help = "Re-encrypt encrypted columns and stored images with the current field key (all or nothing)."

    def handle(self, *args, **opts):
        qn = connection.ops.quote_name
        total = 0
        with transaction.atomic(), connection.cursor() as cur:
            for table, pk, col in _columns():
                cur.execute(f"SELECT {qn(pk)}, {qn(col)} FROM {qn(table)} WHERE {qn(col)} IS NOT NULL AND {qn(col)} <> ''")  # noqa: S608  # nosec B608 - identifiers from model metadata
                for row_pk, token in cur.fetchall():
                    try:
                        new = rotate(token)
                    except InvalidToken as exc:
                        raise CommandError(f"{table}.{col} row {row_pk} cannot be opened with the configured keys — nothing was changed.") from exc
                    cur.execute(f"UPDATE {qn(table)} SET {qn(col)} = %s WHERE {qn(pk)} = %s", [new, row_pk])  # noqa: S608  # nosec B608
                    total += 1
        self.stdout.write(self.style.SUCCESS(f"re-encrypted {total} values; append-only tables keep their original key"))
