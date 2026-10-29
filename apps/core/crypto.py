"""Field-level encryption (DM10001, CS10002).

TRN payloads, medical-condition details and signature blobs are stored as
Fernet tokens (AES-128-CBC + HMAC-SHA256). The key comes from
FIELD_ENCRYPTION_KEY; in development it is derived from SECRET_KEY.
"""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _fernet() -> Fernet:
    key = settings.FIELD_ENCRYPTION_KEY
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(("field-key:" + settings.SECRET_KEY).encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    """Encrypt a string to a Fernet token."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token; returns '' for an unreadable token rather than raising in a template."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


class EncryptedJSONField(models.TextField):
    """JSON value stored encrypted; behaves like a dict/list in Python."""

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return None
        raw = decrypt(value)
        return json.loads(raw) if raw else None

    def to_python(self, value):
        if value is None or isinstance(value, dict | list):
            return value
        try:
            return json.loads(decrypt(value) or value)
        except (TypeError, ValueError):
            return value

    def get_prep_value(self, value):
        if value is None:
            return None
        return encrypt(json.dumps(value, default=str))


class EncryptedTextField(models.TextField):
    """Free text stored encrypted."""

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        return decrypt(value)

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        return encrypt(str(value))
