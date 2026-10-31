"""Saved reports (RP10003) and their schedules (NT10002)."""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class SavedReport(models.Model):
    """A report someone built and named. Either a builder definition or a standard report with its filters."""

    KINDS = [("builder", "Built with the report builder"), ("standard", "Standard report")]

    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    kind = models.CharField(max_length=10, choices=KINDS, default="builder")
    standard_key = models.SlugField(max_length=40, blank=True, help_text="For a standard report: which one.")
    definition = models.JSONField(default=dict, help_text="Builder: dataset, columns, filters, group_by, measure. Standard: its filters.")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="saved_reports")
    shared = models.BooleanField(default=False, help_text="Visible to everyone with reports (each sees only what their role allows).")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def aggregate_only(self):
        """True when the report holds counts only, never one row per person (required for e-mail schedules)."""
        if self.kind == "standard":
            return True
        from .datasets import is_aggregate

        return is_aggregate(self.definition)


class ReportSchedule(models.Model):
    """Send a saved report by e-mail on a schedule. Only reports of counts can be scheduled (data minimisation)."""

    FREQUENCIES = [("daily", "Every day"), ("weekly", "Every Monday"), ("monthly", "First day of the month")]

    report = models.ForeignKey(SavedReport, on_delete=models.CASCADE, related_name="schedules")
    frequency = models.CharField(max_length=10, choices=FREQUENCIES, default="weekly")
    hour = models.PositiveSmallIntegerField(default=7, help_text="Local hour (0–23) the e-mail goes out.")
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="report_subscriptions")
    period_days = models.PositiveSmallIntegerField(default=7, help_text="Each run covers this many days up to the day before.")
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_result = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["report__name"]

    def __str__(self):
        return f"{self.report} · {self.get_frequency_display()}"

    def compute_next_run(self, after=None):
        """Next local run time strictly after `after` (default now)."""
        after = timezone.localtime(after or timezone.now())
        tz = timezone.get_current_timezone()
        day = after.date()
        for _ in range(400):
            candidate = timezone.make_aware(datetime.combine(day, time(self.hour % 24)), tz)
            due = self.frequency == "daily" or (self.frequency == "weekly" and day.weekday() == 0) or (self.frequency == "monthly" and day.day == 1)
            if due and candidate > after:
                return candidate
            day += timedelta(days=1)
        return None
