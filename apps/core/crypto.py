"""Field-level encryption (DM10001, CS10002).

TRN payloads, medical-condition details and signature blobs are stored as
Fernet tokens (AES-128-CBC + HMAC-SHA256). The key comes from
FIELD_ENCRYPTION_KEY; in development it is derived from SECRET_KEY.
"""

import base64
import hashlib
import json
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

log = logging.getLogger(__name__)


def _legacy_key():
    return base64.urlsafe_b64encode(hashlib.sha256(("field-key:" + settings.SECRET_KEY).encode()).digest()).decode()


def _fernet() -> MultiFernet:
    """FIELD_ENCRYPTION_KEY may hold several comma-separated keys: the first encrypts, all of them decrypt (key rotation).

    The key derived from SECRET_KEY is only used when no key is configured (development); it is still tried for
    decryption so values written before a key was configured stay readable until re-encrypted (manage.py rotate_field_keys).
    """
    configured = [k.strip() for k in (settings.FIELD_ENCRYPTION_KEY or "").split(",") if k.strip()]
    keys = configured or [_legacy_key()]
    if configured and getattr(settings, "FIELD_ENCRYPTION_LEGACY_FALLBACK", True):
        keys.append(_legacy_key())  # set FIELD_ENCRYPTION_LEGACY_FALLBACK=0 after running rotate_field_keys
    return MultiFernet([Fernet(k.encode()) for k in keys])


def rotate(token: str) -> str:
    """Re-encrypt a token with the current (first) key."""
    return _fernet().rotate(token.encode()).decode()


def encrypt(value: str) -> str:
    """Encrypt a string to a Fernet token."""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token; returns '' for an unreadable token rather than raising in a template."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        log.error("Encrypted value could not be decrypted: wrong or missing FIELD_ENCRYPTION_KEY?")
        return ""


class Undecryptable(str):
    """A stored value no configured key can open. Reads as empty, and is written back unchanged on save, so a missing
    key never turns into silent data loss: put the right key back and the value is readable again."""

    def __new__(cls, token):
        obj = super().__new__(cls, "")
        obj.token = token
        return obj


class UndecryptableJSON(dict):
    def __init__(self, token):
        super().__init__()
        self.token = token


def _open(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        log.error("Encrypted value could not be decrypted: wrong or missing FIELD_ENCRYPTION_KEY? The stored value is kept unchanged.")
        return None


class EncryptedJSONField(models.TextField):
    """JSON value stored encrypted; behaves like a dict/list in Python."""

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return None
        raw = _open(value)
        if raw is None:
            return UndecryptableJSON(value)
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
        if isinstance(value, UndecryptableJSON):
            return value.token
        return encrypt(json.dumps(value, default=str))


class EncryptedTextField(models.TextField):
    """Free text stored encrypted."""

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        raw = _open(value)
        return Undecryptable(value) if raw is None else raw

    def get_prep_value(self, value):
        if isinstance(value, Undecryptable):
            return value.token
        if value in (None, ""):
            return value
        return encrypt(str(value))


def encrypt_bytes(value: bytes) -> str:
    """Encrypt binary content (images) to a Fernet token."""
    return _fernet().encrypt(value).decode()


def decrypt_bytes(token: str) -> bytes:
    """Decrypt binary content; returns b'' for an unreadable token."""
    try:
        return _fernet().decrypt(token.encode())
    except (InvalidToken, ValueError):
        log.error("Encrypted image could not be decrypted: wrong or missing FIELD_ENCRYPTION_KEY?")
        return b""
