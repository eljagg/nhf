"""Cross-cutting records: centres, parameters, audit events, notifications, integration runs."""

from django.conf import settings
from django.db import models

PARISHES = [
    ("KGN", "Kingston"),
    ("AND", "St Andrew"),
    ("CAT", "St Catherine"),
    ("CLA", "Clarendon"),
    ("MAN", "Manchester"),
    ("ELI", "St Elizabeth"),
    ("WES", "Westmoreland"),
    ("HAN", "Hanover"),
    ("JAM", "St James"),
    ("TRE", "Trelawny"),
    ("ANN", "St Ann"),
    ("MAR", "St Mary"),
    ("POR", "Portland"),
    ("THO", "St Thomas"),
]


class Centre(models.Model):
    """An NHFCard centre (processing and card-collection location)."""

    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    parish = models.CharField(max_length=3, choices=PARISHES)
    is_active = models.BooleanField(default=True)
    prints_cards = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Parameter(models.Model):
    """Parameter-driven configuration editable by the back office (MU10001, US10002)."""

    key = models.SlugField(max_length=80, unique=True)
    value = models.JSONField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    DEFAULTS = {
        "guardian-required-under-age": (18, "Applicants younger than this must have a guardian (BR10004)."),
        "jadep-age": (60, "Age at which the JADEP programme is assigned automatically (BR10005)."),
        "srn-prefix": ("9", "First digit of every Special Registration Number (SR10002)."),
        "work-lock-seconds": (90, "A record is shown as being worked on while the agent's heartbeat is newer than this (OR10010)."),
        "counter-target-minutes": (15, "Target time from entry to dispatch at the counter (PF10001)."),
        "nis-format-regex": (
            r"^([A-Z][0-9]{6}|[0-9]{9})$",
            "Accepted NIS number format (regular expression). Default: one letter + six digits, or nine digits.",
        ),
        "privacy-notice-version": ("2026-10", "Version of the privacy notice applicants consent to (Data Protection Act 2020)."),
        "privacy-notice-text": (
            "The National Health Fund collects your personal details and the medical conditions certified by your doctor to register you for "
            "NHF benefits, produce your NHF Card and process your benefit claims. Your information is shared only with the Tax Administration "
            "(TRN validation), the Medical Council (doctor confirmation), the claims adjudicator and card production, and is kept in line with "
            "the Fund's retention policy. You may ask for a copy of your information or for it to be corrected.",
            "Privacy notice shown on the application form.",
        ),
        "access-log-retention-days": (365, "Days to keep the page-by-page access log."),
        "password-max-age-days": (90, "Staff passwords expire after this many days (0 = never)."),
        "password-history-count": (5, "A new password may not repeat any of the last N passwords."),
        "alert-bulk-view-per-hour": (60, "Raise a security alert when one user opens more member profiles than this in an hour."),
        "alert-failed-logins": (5, "Raise a security alert after this many failed sign-ins for one username within 15 minutes."),
        "alert-failed-logins-address": (20, "Raise a security alert after this many failed sign-ins from one address (any usernames) within 15 minutes."),
        "alert-failed-trn-per-hour": (10, "Raise a security alert when one user's invalid or mismatched TRN checks exceed this in an hour."),
        "dsr-days": (30, "Days allowed to answer a data-subject request."),
        "breach-report-hours": (72, "Hours to report a personal-data breach to the Information Commissioner."),
        "retention-rejected-days": (730, "Rejected/terminated applications are anonymised after this many days."),
    }

    @classmethod
    def get(cls, key, default=None):
        """Return the parameter value, falling back to the documented default."""
        row = cls.objects.filter(key=key).only("value").first()
        if row is not None:
            return row.value
        if key in cls.DEFAULTS:
            return cls.DEFAULTS[key][0]
        return default


class AuditEvent(models.Model):
    """Append-only business audit record: who did what, when, to which record (AL10001)."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    summary = models.CharField(max_length=500, blank=True)
    data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-at"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Audit events are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit events are append-only.")


class Notification(models.Model):
    """Outbound e-mail/SMS/in-app message (NT10001). The provider sits behind an adapter; Phase A records only."""

    CHANNELS = [("sms", "SMS"), ("email", "E-mail"), ("inapp", "In-app")]
    STATUSES = [("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed"), ("previewed", "Preview only")]
    created_at = models.DateTimeField(auto_now_add=True)
    channel = models.CharField(max_length=8, choices=CHANNELS)
    to = models.CharField(max_length=200)
    recipient_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="notifications")
    template = models.SlugField(max_length=60)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    link = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="queued")
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    object_type = models.CharField(max_length=80, blank=True)
    object_id = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.to}: {self.template}"


class IntegrationRun(models.Model):
    """Run log for every call to an external system (IN10003): TRN service, PHI, portal, SMS."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    system = models.CharField(max_length=30, db_index=True)
    operation = models.CharField(max_length=60)
    adapter = models.CharField(max_length=30)
    ok = models.BooleanField(default=True)
    duration_ms = models.PositiveIntegerField(default=0)
    reference = models.CharField(max_length=80, blank=True)
    message = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"{self.system}.{self.operation} {'ok' if self.ok else 'failed'}"
