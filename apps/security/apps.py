from django.apps import AppConfig


class SecurityConfig(AppConfig):
    name = "apps.security"
    label = "security"

    def ready(self):
        from . import signals  # noqa: F401
