"""Staff accounts and temporary role grants (UM10002, UM10007, UM10011)."""

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """A staff user. Directory-sourced accounts (AD/LDAPS, OIDC) map onto this model in Phase B."""

    centre = models.ForeignKey("core.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff")
    staff_number = models.CharField(max_length=20, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True, help_text="Temporary lock set by an administrator (UM10011).")
    lock_reason = models.CharField(max_length=200, blank=True)
    password_changed_at = models.DateTimeField(default=timezone.now, help_text="Drives password expiry.")

    def set_password(self, raw_password):
        """Record when the password changed; the new hash is added to the password history on save."""
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()
        self._password_changed_now = True

    def display_name(self):
        """Full name or username."""
        return self.get_full_name() or self.username

    @property
    def is_temporarily_locked(self):
        """True while an administrator lock is in force."""
        return bool(self.locked_until and self.locked_until > timezone.now())


class TemporaryRole(models.Model):
    """A role granted for a limited period, e.g. cover for a supervisor on leave (UM10007)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="temporary_roles")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    reason = models.CharField(max_length=200)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.user} → {self.group} until {self.expires_at:%Y-%m-%d %H:%M}"

    @property
    def is_active(self):
        """True between start and expiry unless revoked."""
        now = timezone.now()
        return self.revoked_at is None and self.starts_at <= now < self.expires_at
