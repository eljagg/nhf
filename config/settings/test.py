from .base import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ["*"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed; tests only
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
AXES_ENABLED = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
PORTAL_SHARED_SECRET = "test-portal-secret"  # noqa: S105  # nosec B105

MFA_REQUIRED = False  # role-based enforcement still applies; all-staff enforcement has its own tests
LDAP = {**LDAP, "ENABLED": False}  # noqa: F405
OIDC = {**OIDC, "ENABLED": False}  # noqa: F405
