"""Member Registration System for the National Health Fund — base settings.

Tender: National Health Fund RFB No. NHF/MRS/2026-09 (GoJEP 1021/1473),
Member Registration System and Support Services.

Environment-specific values come from environment variables (see .env.example).
Never put secrets in this file.
"""

import os
from datetime import timedelta
from pathlib import Path

import environ
from csp.constants import NONCE, SELF

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    REDIS_URL=(str, ""),
    EMAIL_URL=(str, "consolemail://"),
    DEFAULT_FROM_EMAIL=(str, "NHF Member Registration <no-reply@nhf.org.jm>"),
    SITE_URL=(str, "http://localhost:8000"),
    SESSION_IDLE_MINUTES=(int, 30),
    SESSION_ABSOLUTE_HOURS=(int, 10),
    AXES_FAILURE_LIMIT=(int, 5),
    AXES_COOLOFF_MINUTES=(int, 15),
    TRN_ADAPTER=(str, "mock"),
    TRN_SOAP_WSDL=(str, ""),
    TRN_SOAP_USERNAME=(str, ""),
    TRN_SOAP_PASSWORD=(str, ""),
    TRN_TIMEOUT_SECONDS=(int, 10),
    PORTAL_SHARED_SECRET=(str, ""),
    FIELD_ENCRYPTION_KEY=(str, ""),
    MFA_REQUIRED=(bool, True),
    MFA_DEMO_PRIVILEGED_ONLY=(bool, False),
    LDAP_ENABLED=(bool, False),
    LDAP_SERVER_URI=(str, ""),
    LDAP_BIND_DN=(str, ""),
    LDAP_BIND_PASSWORD=(str, ""),
    LDAP_USER_SEARCH_BASE=(str, ""),
    LDAP_USER_FILTER=(str, "(&(objectClass=user)(sAMAccountName={username}))"),
    LDAP_GROUP_SEARCH_BASE=(str, ""),
    LDAP_NESTED_GROUPS=(bool, True),
    LDAP_CA_CERT_FILE=(str, ""),
    LDAP_TIMEOUT=(int, 5),
    LDAP_ALLOW_PLAIN=(bool, False),
    OIDC_ENABLED=(bool, False),
    OIDC_TENANT_ID=(str, ""),
    OIDC_CLIENT_ID=(str, ""),
    OIDC_CLIENT_SECRET=(str, ""),
    OIDC_AUTHORITY=(str, ""),
    OIDC_GROUPS_CLAIM=(str, "groups"),
    OIDC_BUTTON_LABEL=(str, "Sign in with Microsoft"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-only-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL")
# Railway sets RAILWAY_PUBLIC_DOMAIN; trust it automatically so a staging deploy needs no host settings.
_railway_domain = env("RAILWAY_PUBLIC_DOMAIN", default="")
if _railway_domain:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _railway_domain]
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{_railway_domain}"]
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "localhost", "127.0.0.1"]  # container health check

# Product name and optional builder credit shown on screens; set per environment, no code change.
PRODUCT_NAME = env("PRODUCT_NAME", default="Registry Platform")
BUILT_BY = env("BUILT_BY", default="")
EDITION_NAME = "Member Registration"
CLIENT_NAME = "National Health Fund"
VERSION = "0.3.0"

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.humanize",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "django_filters",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "axes",
    "csp",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.rules",
    "apps.identity",
    "apps.doctors",
    "apps.members",
    "apps.cards",
    "apps.interactions",
    "apps.intake",
    "apps.api",
    "apps.security",
    "apps.privacy",
    "apps.directory",
    "apps.reports",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.accounts.middleware.SessionIdleMiddleware",
    "apps.accounts.middleware.MFAEnforcementMiddleware",
    "apps.directory.middleware.DirectoryRecheckMiddleware",
    "apps.core.middleware.CurrentUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "apps.security.middleware.PasswordExpiryMiddleware",
    "apps.security.middleware.AccessLogMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.site",
            ],
        },
    }
]

# ----------------------------------------------------------------------------
# Database — PostgreSQL 16, system of record
# ----------------------------------------------------------------------------
DATABASES = {"default": env.db_url("DATABASE_URL", default="postgres://nhf:nhf@localhost:5432/nhf")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DATABASES["default"].setdefault("OPTIONS", {})
DATABASES["default"]["OPTIONS"].update({"connect_timeout": 5})
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ----------------------------------------------------------------------------
# Cache / Celery. Without REDIS_URL the app runs single-process: local-memory cache,
# database sessions and Celery tasks executed inline (Phase A staging needs one service only).
# ----------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": "nhf",
            "TIMEOUT": 300,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=not bool(REDIS_URL))
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = "America/Jamaica"
CELERY_TASK_ROUTES = {
    "apps.identity.tasks.*": {"queue": "identity"},
    "apps.core.tasks.send_notification": {"queue": "notify"},
}
CELERY_BEAT_SCHEDULE = {
    "print-queue-daily-reset": {"task": "apps.cards.tasks.daily_queue_reset", "schedule": timedelta(hours=24)},
    "jadep-at-60-sweep": {"task": "apps.members.tasks.jadep_sweep", "schedule": timedelta(hours=24)},
    "expire-temporary-roles": {"task": "apps.accounts.tasks.expire_temporary_roles", "schedule": timedelta(minutes=15)},
    "retention-sweep": {"task": "apps.privacy.tasks.retention_sweep", "schedule": timedelta(hours=24)},
    "directory-sync": {"task": "apps.directory.tasks.sync_directory_users", "schedule": timedelta(hours=1)},
    "id-expiry-check": {"task": "apps.core.tasks.check_id_expiry", "schedule": timedelta(hours=24)},
    "practitioner-recheck": {"task": "apps.doctors.tasks.recheck_registers", "schedule": timedelta(hours=24)},
    "scheduled-reports": {"task": "apps.reports.tasks.send_due_reports", "schedule": timedelta(minutes=15)},
    "escalate-overdue": {"task": "apps.reports.tasks.escalate_overdue", "schedule": timedelta(hours=1)},
}

# ----------------------------------------------------------------------------
# Authentication (UM10001–UM10011)
# ----------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.directory.backends.ActiveDirectoryBackend",  # no-op unless LDAP_ENABLED
    "django.contrib.auth.backends.ModelBackend",  # local accounts (break-glass administrators, demo users)
]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"
OTP_TOTP_ISSUER = "NHF Member Registration"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.ComplexityValidator"},
    {"NAME": "apps.accounts.validators.PasswordHistoryValidator"},
]
# Two-step sign-in (UM10004). On by default for every staff account: anyone who can open member records handles personal and
# health data under the Data Protection Act. MFA_REQUIRED_ROLES always need it, whatever the settings below say.
MFA_REQUIRED = env("MFA_REQUIRED")
# Demonstration convenience only: with DEMO_MODE on, MFA_DEMO_PRIVILEGED_ONLY=1 limits it to MFA_REQUIRED_ROLES. Ignored when DEMO_MODE is off.
MFA_DEMO_PRIVILEGED_ONLY = env("MFA_DEMO_PRIVILEGED_ONLY")
MFA_REQUIRED_ROLES = ["manager", "ict_admin", "db_admin", "dpo"]

AXES_FAILURE_LIMIT = env("AXES_FAILURE_LIMIT")
AXES_COOLOFF_TIME = timedelta(minutes=env("AXES_COOLOFF_MINUTES"))
# Lock the account being attacked, not the counter PC: centres share PCs and one public address, so an address-based lock
# would lock out every agent at a centre after one person mistypes. Address-wide attempts raise a security alert instead.
AXES_LOCKOUT_PARAMETERS = ["username"]
SILENCED_SYSTEM_CHECKS = ["axes.W006"]  # deliberate: see the comment above
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked_out.html"

SESSION_ENGINE = "django.contrib.sessions.backends.cache" if REDIS_URL else "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env("SESSION_ABSOLUTE_HOURS") * 3600
SESSION_IDLE_MINUTES = env("SESSION_IDLE_MINUTES")
CSRF_COOKIE_HTTPONLY = False  # htmx reads the token from the meta tag

# ----------------------------------------------------------------------------
# Security headers / CSP
# ----------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),
        "script-src": (SELF, NONCE),
        "style-src": ("'self'", "'unsafe-inline'"),
        "img-src": ("'self'", "data:"),
        "font-src": ("'self'",),
        "connect-src": ("'self'",),
        "frame-ancestors": ("'none'",),
        "form-action": ("'self'",),
        "base-uri": ("'self'",),
        "object-src": ("'none'",),
    }
}

# Field-level encryption for TRN payloads, medical conditions, signatures (DM10001, CS10002).
# Separate key in production; derived from SECRET_KEY when unset (development only).
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY")
FIELD_ENCRYPTION_LEGACY_FALLBACK = os.environ.get("FIELD_ENCRYPTION_LEGACY_FALLBACK", "1") == "1"

# ----------------------------------------------------------------------------
# Static files
# ----------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))

vars().update(env.email_url("EMAIL_URL"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ----------------------------------------------------------------------------
# REST API (IN10001, MU10002)
# ----------------------------------------------------------------------------
# Number of proxies in front of the app that append to X-Forwarded-For (Railway edge / NHF load balancer = 1).
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0"))
MAX_REQUEST_BYTES = 25 * 1024 * 1024  # largest upload is a 20 MB register extract
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

REST_FRAMEWORK = {
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"user": "600/min", "portal": "120/min"},
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
SPECTACULAR_SETTINGS = {
    "TITLE": f"{PRODUCT_NAME} — Member Registration API",
    "DESCRIPTION": "Member, application-tracking and online-intake API for the NHF Member Registration System.",
    "VERSION": VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

# ----------------------------------------------------------------------------
# Integrations (Integration Hub adapters; mock in Phase A)
# ----------------------------------------------------------------------------
TRN_ADAPTER = env("TRN_ADAPTER")  # mock | soap
TRN_SOAP = {
    "WSDL": env("TRN_SOAP_WSDL"),
    "USERNAME": env("TRN_SOAP_USERNAME"),
    "PASSWORD": env("TRN_SOAP_PASSWORD"),
    "TIMEOUT": env("TRN_TIMEOUT_SECONDS"),
}
PORTAL_SHARED_SECRET = env("PORTAL_SHARED_SECRET")

# Directory sign-in (UM10005 Active Directory over LDAPS; UM10006 Entra ID single sign-on). Secrets only from the environment.
LDAP = {
    "ENABLED": env("LDAP_ENABLED"),
    "SERVER_URI": env("LDAP_SERVER_URI"),  # ldaps://dc1.nhf.local:636 ; "mock://demo" = built-in demonstration directory
    "BIND_DN": env("LDAP_BIND_DN"),
    "BIND_PASSWORD": env("LDAP_BIND_PASSWORD"),
    "USER_SEARCH_BASE": env("LDAP_USER_SEARCH_BASE"),
    "USER_FILTER": env("LDAP_USER_FILTER"),
    "GROUP_SEARCH_BASE": env("LDAP_GROUP_SEARCH_BASE"),
    "NESTED_GROUPS": env("LDAP_NESTED_GROUPS"),
    "CA_CERT_FILE": env("LDAP_CA_CERT_FILE"),
    "TIMEOUT": env("LDAP_TIMEOUT"),
    "ALLOW_PLAIN": env("LDAP_ALLOW_PLAIN"),
}
OIDC = {
    "ENABLED": env("OIDC_ENABLED"),
    "TENANT_ID": env("OIDC_TENANT_ID"),
    "CLIENT_ID": env("OIDC_CLIENT_ID"),
    "CLIENT_SECRET": env("OIDC_CLIENT_SECRET"),
    "AUTHORITY": env("OIDC_AUTHORITY") or (f"https://login.microsoftonline.com/{env('OIDC_TENANT_ID')}/v2.0" if env("OIDC_TENANT_ID") else ""),
    "GROUPS_CLAIM": env("OIDC_GROUPS_CLAIM"),
    "BUTTON_LABEL": env("OIDC_BUTTON_LABEL"),
}

# ----------------------------------------------------------------------------
# Council registers (doctors: Medical Council of Jamaica; nurses: Nursing Council of Jamaica)
# MODE local = the local copy loaded from the council's extract; https = the council's verification service.
# ----------------------------------------------------------------------------
PRACTITIONER_REGISTERS = {
    council: {
        "MODE": os.environ.get(f"{council.upper()}_REGISTER_MODE", "local"),
        "URL": os.environ.get(f"{council.upper()}_REGISTER_URL", ""),
        "API_KEY": os.environ.get(f"{council.upper()}_REGISTER_API_KEY", ""),
        "API_KEY_HEADER": os.environ.get(f"{council.upper()}_REGISTER_API_KEY_HEADER", "X-API-Key"),
        "TIMEOUT": int(os.environ.get(f"{council.upper()}_REGISTER_TIMEOUT", "6")),
        "SIMULATE_DOWN": False,
    }
    for council in ("mcj", "ncj")
}

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "America/Jamaica"
USE_I18N = False
USE_TZ = True
DATE_FORMAT = "j M Y"
DATETIME_FORMAT = "j M Y, H:i"

# Informational lines go to stdout and warnings/errors to stderr, so hosting dashboards (Railway shows stderr as [err])
# only flag real problems. A refused page (403) is logged as one line, without a traceback.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "below_warning": {"()": "apps.core.logfilters.BelowWarning"},
        "quiet_403": {"()": "apps.core.logfilters.Quiet403"},
    },
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {
        "stdout": {"class": "logging.StreamHandler", "stream": "ext://sys.stdout", "formatter": "plain", "filters": ["below_warning"]},
        "stderr": {"class": "logging.StreamHandler", "stream": "ext://sys.stderr", "formatter": "plain", "level": "WARNING", "filters": ["quiet_403"]},
    },
    "root": {"handlers": ["stdout", "stderr"], "level": "INFO"},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
        "axes": {"level": "WARNING"},  # sign-ins are already in the audit trail and session records
    },
}

# Shows the "synthetic demo data" marker and enables the portal simulator. Off on NHF's servers.
DEMO_MODE = env.bool("DEMO_MODE", default=True)
