"""Password rules beyond Django's built-ins."""

from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError

from apps.core.models import Parameter


class PasswordHistoryValidator:
    """A new password may not match any of the user's last N passwords."""

    def validate(self, password, user=None):
        if user is None or not getattr(user, "pk", None):
            return
        keep = int(Parameter.get("password-history-count"))
        for old in user.password_history.all()[:keep]:
            if check_password(password, old.password):
                raise ValidationError(f"This password was used recently. Choose one you have not used in your last {keep} passwords.", code="password_reused")

    def get_help_text(self):
        return "Your password cannot repeat one of your recent passwords."


class ComplexityValidator:
    """At least one letter and one digit or symbol."""

    def validate(self, password, user=None):
        if not any(c.isalpha() for c in password) or not any(not c.isalpha() for c in password):
            raise ValidationError("Use letters and at least one number or symbol.", code="password_simple")

    def get_help_text(self):
        return "Use letters and at least one number or symbol."
