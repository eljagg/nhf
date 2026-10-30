from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SILENCED_SYSTEM_CHECKS = ["security.W021", "axes.W006"]  # HSTS preload is a domain-owner decision for NHF, not an application default

# Behind exactly one proxy (Railway's edge, or NHF's load balancer): only its X-Forwarded-For entry is trusted.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=1)
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": TRUSTED_PROXY_COUNT}  # noqa: F405

# Demonstration features (simulated portal submissions, demo directory, relaxed two-step for counter roles,
# synthetic seed data) are OFF in production unless DEMO_MODE=1 is set on purpose (staging/demo only).
DEMO_MODE = env.bool("DEMO_MODE", default=False)

# Field encryption must have its own key in production: never derived from SECRET_KEY.
if not env("FIELD_ENCRYPTION_KEY"):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
        'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" — and never change it once data exists '
        "(add the new key in front of the old one, comma-separated, to rotate)."
    )

SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
