"""User tracking and security records: access log, sessions, password history, security alerts."""

from django.conf import settings
from django.db import models


class AccessLog(models.Model):
    """One row per page or API request by a signed-in user: who, when, what, which record, from where."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="access_logs")
    session_ref = models.CharField(max_length=12, blank=True, help_text="Short hash of the session, to group a sign-in's requests.")
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    route = models.CharField(max_length=80, blank=True)
    status = models.PositiveSmallIntegerField(default=200)
    duration_ms = models.PositiveIntegerField(default=0)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    object_type = models.CharField(max_length=20, blank=True, db_index=True)
    object_ref = models.CharField(max_length=40, blank=True, db_index=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["user", "at"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.method} {self.path}"


class UserSession(models.Model):
    """A signed-in session, so administrators can see where a user is signed in and end it."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tracked_sessions")
    session_key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.user} since {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def device(self):
        """Short browser/OS description from the user agent."""
        ua = self.user_agent
        browser = next((b for b in ("Edg", "Chrome", "Firefox", "Safari") if b in ua), "Browser")
        system = next((s for s in ("Windows", "Mac OS", "Android", "iPhone", "Linux") if s in ua), "")
        return f"{'Edge' if browser == 'Edg' else browser}{' on ' + system if system else ''}"


class PasswordHistory(models.Model):
    """Hashes of previous passwords, so a reset cannot reuse a recent one."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="password_history")
    password = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Password history for {self.user_id} at {self.created_at:%Y-%m-%d}"


class SecurityAlert(models.Model):
    """Something that needs a person to look at it: repeated failed sign-ins, bulk record viewing, TRN failures."""

    KINDS = [
        ("failed_logins", "Repeated failed sign-ins"),
        ("bulk_viewing", "Unusual number of member records opened"),
        ("trn_failures", "Unusual number of failed TRN checks"),
        ("account_locked", "Account locked"),
        ("failed_mfa", "Repeated wrong two-step codes"),
        ("mfa_reset", "Two-step sign-in reset by an administrator"),
        ("directory", "Directory account change"),
        ("sessions_revoked", "Sessions ended by an administrator"),
        ("rate_limit", "Lookup limit exceeded"),
    ]
    SEVERITIES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=20, choices=KINDS)
    severity = models.CharField(max_length=6, choices=SEVERITIES, default="medium")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    subject = models.CharField(max_length=150, blank=True, help_text="Username or address the alert is about.")
    message = models.CharField(max_length=400)
    data = models.JSONField(default=dict, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return self.message
