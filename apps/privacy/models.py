"""Data Protection Act 2020 records: processing register, data-subject requests, breach register, retention runs."""

from datetime import timedelta

from django.conf import settings
from django.db import connection, models
from django.utils import timezone


def _next_ref(prefix, seq):
    with connection.cursor() as cur:
        cur.execute(f"SELECT nextval('{seq}')")  # noqa: S608 - fixed sequence names
        n = cur.fetchone()[0]
    return f"{prefix}-{timezone.localdate().year}-{n:04d}"


def next_dsr_reference():
    """DSR-YYYY-NNNN."""
    return _next_ref("DSR", "privacy_dsr_seq")


def next_breach_reference():
    """BR-YYYY-NNNN."""
    return _next_ref("BR", "privacy_breach_seq")


class ProcessingActivity(models.Model):
    """Record of processing activities: what personal data the system handles, why, on what basis, shared with whom, for how long."""

    name = models.CharField(max_length=120, unique=True)
    purpose = models.TextField()
    lawful_basis = models.CharField(max_length=200)
    data_subjects = models.CharField(max_length=200)
    data_categories = models.TextField()
    sensitive = models.BooleanField(default=False, help_text="Includes health or other sensitive personal data.")
    recipients = models.TextField(blank=True)
    retention = models.CharField(max_length=200)
    security_measures = models.TextField(blank=True)
    transfers_outside_jamaica = models.CharField(max_length=200, default="None — hosted on NHF's own infrastructure")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "processing activities"

    def __str__(self):
        return self.name


class DataSubjectRequest(models.Model):
    """A person asking to see, correct or object to the use of their data."""

    KINDS = [
        ("access", "Copy of my data (access)"),
        ("correction", "Correct my data"),
        ("objection", "Object to / restrict processing"),
        ("erasure", "Delete my data"),
    ]
    STATUSES = [("open", "Open"), ("in_progress", "In progress"), ("completed", "Completed"), ("refused", "Refused (with reasons)")]
    CHANNELS = [("counter", "At a centre"), ("email", "E-mail"), ("letter", "Letter"), ("phone", "Telephone")]
    reference = models.CharField(max_length=20, unique=True, default=next_dsr_reference)
    member = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.SET_NULL, related_name="data_requests")
    requester_name = models.CharField(max_length=120)
    requester_contact = models.CharField(max_length=120, blank=True)
    identity_checked = models.BooleanField(default=False, help_text="Requester's identity verified (ID seen / TRN confirmed).")
    kind = models.CharField(max_length=12, choices=KINDS)
    channel = models.CharField(max_length=8, choices=CHANNELS, default="counter")
    details = models.TextField(blank=True)
    received_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUSES, default="open")
    response = models.TextField(blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    export_count = models.PositiveSmallIntegerField(default=0)
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["status", "due_at"]

    def __str__(self):
        return self.reference

    @property
    def is_open(self):
        """Still to be answered."""
        return self.status in ("open", "in_progress")

    @property
    def overdue(self):
        """Past the due date and still open."""
        return self.is_open and timezone.now() > self.due_at

    @property
    def days_left(self):
        """Whole days until due (negative when overdue)."""
        return (self.due_at - timezone.now()).days


class Breach(models.Model):
    """Personal-data breach register, with the clock for reporting to the Information Commissioner."""

    SEVERITIES = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
    STATUSES = [("open", "Open — investigating"), ("contained", "Contained"), ("reported", "Reported to the Commissioner"), ("closed", "Closed")]
    reference = models.CharField(max_length=20, unique=True, default=next_breach_reference)
    title = models.CharField(max_length=160)
    discovered_at = models.DateTimeField(default=timezone.now)
    occurred_at = models.DateTimeField(null=True, blank=True)
    description = models.TextField()
    data_categories = models.CharField(max_length=300, help_text="e.g. names, TRNs, medical conditions")
    subjects_affected = models.PositiveIntegerField(default=0, help_text="Best estimate of people affected.")
    severity = models.CharField(max_length=6, choices=SEVERITIES, default="medium")
    status = models.CharField(max_length=10, choices=STATUSES, default="open")
    contained_at = models.DateTimeField(null=True, blank=True)
    reported_to_commissioner_at = models.DateTimeField(null=True, blank=True)
    subjects_notified_at = models.DateTimeField(null=True, blank=True)
    actions = models.TextField(blank=True, help_text="Containment and remedial actions taken.")
    logged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-discovered_at"]
        verbose_name_plural = "breaches"

    def __str__(self):
        return f"{self.reference} {self.title}"

    @property
    def report_deadline(self):
        """Discovery time plus the configured reporting window."""
        from apps.core.models import Parameter

        return self.discovered_at + timedelta(hours=int(Parameter.get("breach-report-hours")))

    @property
    def report_overdue(self):
        """Not yet reported and past the deadline."""
        return self.reported_to_commissioner_at is None and timezone.now() > self.report_deadline

    @property
    def hours_left(self):
        """Hours until the reporting deadline (negative when overdue)."""
        return int((self.report_deadline - timezone.now()).total_seconds() // 3600)


class RetentionRun(models.Model):
    """One run of the retention sweep and what it did."""

    at = models.DateTimeField(auto_now_add=True)
    dry_run = models.BooleanField(default=False)
    results = models.JSONField(default=dict)
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return f"Retention run {self.at:%Y-%m-%d %H:%M}{' (preview)' if self.dry_run else ''}"
