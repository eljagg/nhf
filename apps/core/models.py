"""Cross-cutting records: centres, parameters, audit events, notifications, integration runs."""

import uuid

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

    KINDS = [("head_office", "Head Office"), ("drug_serv", "Drug Serv pharmacy")]
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=120)
    parish = models.CharField(max_length=3, choices=PARISHES)
    kind = models.CharField(max_length=12, choices=KINDS, default="drug_serv")
    address = models.CharField(max_length=200, blank=True)
    hours = models.CharField("opening hours", max_length=200, blank=True)
    phone = models.CharField(max_length=120, blank=True)
    same_day = models.BooleanField("same-day card (about 15 minutes)", default=True)
    is_active = models.BooleanField(default=True)
    prints_cards = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# Security floors and ceilings: a back-office edit can never switch a control off. (min, max)
PARAMETER_LIMITS = {
    "access-log-retention-days": (180, 3650),
    "staff-id-retention-days": (90, 3650),
    "retention-rejected-days": (365, 3650),
    "directory-recheck-minutes": (5, 60),
    "register-recheck-days": (1, 90),
    "id-expiry-warning-days": (7, 120),
    "password-max-age-days": (0, 365),
    "password-history-count": (3, 24),
    "alert-failed-logins": (3, 20),
    "alert-failed-logins-address": (5, 100),
    "alert-failed-mfa": (3, 20),
    "alert-bulk-view-per-hour": (10, 500),
    "alert-failed-trn-per-hour": (3, 100),
    "limit-trn-screen-per-hour": (5, 200),
    "limit-register-check-per-hour": (5, 300),
    "dsr-days": (1, 30),
    "breach-report-hours": (1, 72),
}
# Only application administrators and the DPO may change these in the back office.
SECURITY_PARAMETERS = set(PARAMETER_LIMITS) - {"retention-rejected-days", "register-recheck-days", "dsr-days", "id-expiry-warning-days"}


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
        "child-double-subsidy-under-age": (19, "Children younger than this get double the NHF subsidy on medication and devices."),
        "mail-address": ("National Health Fund, P.O. Box 412, Kingston 10", "Where paper applications are mailed (shown on the public How to apply page)."),
        "mail-turnaround": ("3 to 4 weeks", "Turnaround promised for mailed applications (How to apply page)."),
        "same-day-minutes": (15, "Card turnaround promised for complete forms handed in at a card centre."),
        "record-update-hours": (24, "Medical-record updates are completed within this many hours (form rev. 12, back page)."),
        "toll-free-numbers": ("(888) 342-5643 · (876) 906-1106", "Telephone numbers shown to the public."),
        "srn-prefix": ("9", "First digit of every Special Registration Number (SR10002)."),
        "directory-recheck-minutes": (
            15,
            "Signed-in Active Directory users are re-checked against AD this often; disabled accounts are signed out (0 turns it off).",
        ),
        "id-expiry-warning-days": (30, "Staff and supervisors are told this many days before an ID on file expires."),
        "register-recheck-days": (30, "Confirmed doctors and nurses are re-checked against their council register this often (nightly batch)."),
        "work-lock-seconds": (90, "A record is shown as being worked on while the agent's heartbeat is newer than this (OR10010)."),
        "counter-target-minutes": (15, "Target time from entry to dispatch at the counter (PF10001)."),
        "nis-format-regex": (
            r"^[A-Z][0-9]{6}$",
            "Accepted NIS number format (regular expression). Default: one letter followed by six digits, e.g. G721675.",
        ),
        "privacy-notice-version": ("2026-11", "Version of the privacy notice applicants consent to (Data Protection Act 2020)."),
        "privacy-notice-text": (
            "The National Health Fund collects your personal details and the medical conditions certified by your doctor to register you for "
            "NHF benefits, produce your NHF Card and process your benefit claims. Your health information is sensitive personal data and is "
            "processed with your written consent. It is shared only with Tax Administration Jamaica (TRN validation), the Medical Council and "
            "Nursing Council (confirming the health professional who certified your form), the claims adjudicator and card production, and is "
            "kept in line with the Fund's retention schedule. Eligibility checks are assisted by the system, but every decision is made by NHF "
            "staff. Under the Data Protection Act 2020 you may ask for a copy of your information, ask for it to be corrected, object to or ask "
            "us to restrict its use, and ask for any decision to be reviewed by a person. Contact the Fund's Data Protection Officer at any NHF "
            "centre. You may also complain to the Office of the Information Commissioner.",
            "Privacy notice shown on the application form.",
        ),
        "access-log-retention-days": (365, "Days to keep the page-by-page access log."),
        "password-max-age-days": (90, "Staff passwords expire after this many days (0 = never)."),
        "password-history-count": (5, "A new password may not repeat any of the last N passwords."),
        "alert-bulk-view-per-hour": (60, "Raise a security alert when one user opens more member profiles than this in an hour."),
        "alert-failed-logins": (5, "Raise a security alert after this many failed sign-ins for one username within 15 minutes."),
        "alert-failed-logins-address": (20, "Raise a security alert after this many failed sign-ins from one address (any usernames) within 15 minutes."),
        "alert-failed-mfa": (5, "Raise a security alert after this many wrong two-step codes for one user within 15 minutes."),
        "limit-trn-screen-per-hour": (
            40,
            "Most TRN screenings (without an application) one user may run in an hour; beyond this they are refused and an alert raised.",
        ),
        "limit-register-check-per-hour": (60, "Most council register checks one user may run by hand in an hour."),
        "alert-failed-trn-per-hour": (10, "Raise a security alert when one user's invalid or mismatched TRN checks exceed this in an hour."),
        "dsr-days": (30, "Days allowed to answer a data-subject request."),
        "dpo-name": ("", "Data Protection Officer's name, used in breach notices and the privacy notice."),
        "dpo-email": ("", "Data Protection Officer's e-mail address."),
        "dpo-phone": ("", "Data Protection Officer's telephone number."),
        "dpa-registration-number": ("", "The Fund's registration number with the Office of the Information Commissioner."),
        "dpa-registration-expiry": ("", "Date the registration must be renewed (YYYY-MM-DD); the privacy dashboard warns 60 days before."),
        "staff-id-retention-days": (365, "ID number, ID picture and photo of a disabled staff account are erased this many days after it was disabled."),
        "breach-report-hours": (72, "Hours to report a personal-data breach to the Information Commissioner."),
        "retention-rejected-days": (730, "Rejected/terminated applications are anonymised after this many days."),
    }

    @staticmethod
    def clamp(key, value):
        """Hold a numeric security parameter inside its allowed range."""
        if key not in PARAMETER_LIMITS:
            return value
        low, high = PARAMETER_LIMITS[key]
        try:
            number = int(value)
        except (TypeError, ValueError):
            return Parameter.DEFAULTS[key][0]
        return max(low, min(high, number))

    @classmethod
    def get(cls, key, default=None):
        """Return the parameter value, falling back to the documented default; security limits are always enforced."""
        row = cls.objects.filter(key=key).only("value").first()
        if row is not None:
            return cls.clamp(key, row.value)
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


class StoredImage(models.Model):
    """A photo or ID image, re-encoded on upload (metadata stripped) and stored encrypted in the database.

    Kept in PostgreSQL rather than a media folder so images survive redeploys, are covered by the database backup,
    and are encrypted at rest with the field key like other personal data.
    """

    KINDS = [
        ("staff_photo", "Staff profile photo"),
        ("staff_id", "Staff ID document"),
        ("practitioner_photo", "Doctor / nurse photo"),
        ("signature", "Applicant / guardian signature"),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=20, choices=KINDS)
    data = models.TextField(help_text="Fernet token of the JPEG bytes.")
    content_type = models.CharField(max_length=30, default="image/jpeg")
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_kind_display()} {self.width}×{self.height}"
