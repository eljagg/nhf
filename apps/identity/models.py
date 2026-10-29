"""Identity verification records: TRN validations, SRN issues, and the synthetic Tax Office register used by the mock adapter."""

from django.conf import settings
from django.db import models

from apps.core.crypto import EncryptedJSONField


class TrnValidation(models.Model):
    """One call to the TRN service and its outcome (TV10001–TV10008).

    Decisions never read an old row: every validation is a fresh call (TV10008); old rows are audit only.
    """

    STATUSES = [
        ("pending", "Checking"),
        ("valid", "TRN valid"),
        ("invalid", "TRN not found"),
        ("unavailable", "Service unavailable"),
    ]
    MATCH = [("", "Not compared"), ("match", "Matches the form"), ("mismatch", "Does not match the form"), ("screen", "Screening only")]
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    trn = models.CharField(max_length=9, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    purpose = models.CharField(max_length=20, default="application")  # application | change | screen | portal | refresh
    status = models.CharField(max_length=12, choices=STATUSES, default="pending")
    adapter = models.CharField(max_length=20, blank=True)
    payload = EncryptedJSONField(null=True, blank=True)  # identity returned by TAJ, encrypted at rest
    form_identity = EncryptedJSONField(null=True, blank=True)  # what the paper form says, for the match step
    match_result = models.CharField(max_length=10, choices=MATCH, blank=True)
    differences = models.JSONField(default=list, blank=True)
    message = models.CharField(max_length=300, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"TRN {self.trn} {self.status}"

    @property
    def is_done(self):
        """False while the worker is still calling the service."""
        return self.status != "pending"


class SrnIssue(models.Model):
    """Special Registration Number request and approval (SR10001–SR10006)."""

    STATUSES = [("requested", "Awaiting approval"), ("approved", "Approved — SRN issued"), ("declined", "Declined")]
    created_at = models.DateTimeField(auto_now_add=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60)
    dob = models.DateField()
    gender = models.CharField(max_length=1, choices=[("M", "Male"), ("F", "Female")])
    reason = models.CharField(max_length=300, help_text="Why the applicant has no validated TRN.")
    duplicate_check = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="requested")
    srn = models.CharField(max_length=9, unique=True, null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.srn or f"SRN request {self.pk}"

    @property
    def full_name(self):
        """Display name."""
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)


class TajIdentity(models.Model):
    """SYNTHETIC stand-in for the Tax Administration Jamaica TRN register, read only by the mock adapter.

    Never populated in production: the real adapter calls the ICT Authority's TRN Validation Web Service.
    """

    trn = models.CharField(max_length=9, unique=True)
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60)
    dob = models.DateField()
    gender = models.CharField(max_length=1)
    address_line1 = models.CharField(max_length=120, blank=True)
    address_line2 = models.CharField(max_length=120, blank=True)
    parish = models.CharField(max_length=3, blank=True)
    demo_note = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["trn"]
        verbose_name = "synthetic TAJ identity"

    def __str__(self):
        return f"{self.trn} {self.first_name} {self.last_name}"
