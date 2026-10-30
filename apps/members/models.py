"""Member domain: members, applications (new and change forms), guardians, conditions, enrolments."""

from django.conf import settings
from django.db import connection, models
from django.utils import timezone

from apps.core.crypto import EncryptedTextField
from apps.core.models import PARISHES

GENDERS = [("M", "Male"), ("F", "Female")]
SEVERITIES = [("mild", "Mild"), ("moderate", "Moderate"), ("severe", "Severe")]
PROTECTED_FIELDS = ("first_name", "middle_name", "last_name", "dob", "gender")


def next_member_number():
    """MR10003: unique member number from a database sequence (format confirmed with NHF at inception)."""
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('members_member_number_seq')")
        return str(cur.fetchone()[0])


def next_tracking_number():
    """Tracking number NHF-A-YYYY-NNNNNNN (MR10001)."""
    with connection.cursor() as cur:
        cur.execute("SELECT nextval('members_tracking_seq')")
        seq = cur.fetchone()[0]
    return f"NHF-A-{timezone.localdate().year}-{seq:07d}"


class Member(models.Model):
    """An NHF beneficiary.

    Name, date of birth and gender are protected: a database trigger rejects any change to them unless the
    Identity Verification module is applying a TRN payload in the same transaction (BR10001–BR10003).
    """

    STATUSES = [("active", "Active"), ("inactive", "Inactive"), ("deceased", "Deceased")]
    member_number = models.CharField(max_length=12, unique=True)
    trn = models.CharField("TRN / SRN", max_length=9, unique=True)
    is_srn = models.BooleanField(default=False)
    nis_number = models.CharField("NIS number", max_length=12, blank=True, db_index=True, help_text="National Insurance Scheme number (optional).")
    consent_at = models.DateTimeField(null=True, blank=True, help_text="When the member consented to processing (Data Protection Act 2020).")
    consent_version = models.CharField(max_length=20, blank=True)
    processing_restricted_at = models.DateTimeField(
        null=True, blank=True, help_text="Set by the DPO when the member objects to / asks to restrict processing (Data Protection Act 2020)."
    )
    processing_restriction_reason = models.CharField(max_length=300, blank=True)
    srn_annotation = models.CharField(max_length=120, blank=True, help_text="Shown with the number when it is an SRN (SR10005).")
    first_name = models.CharField(max_length=60)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60)
    dob = models.DateField("Date of birth")
    gender = models.CharField(max_length=1, choices=GENDERS)
    phone_mobile = models.CharField(max_length=20, blank=True)
    phone_home = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address_line1 = models.CharField(max_length=120, blank=True)
    address_line2 = models.CharField(max_length=120, blank=True)
    parish = models.CharField(max_length=3, choices=PARISHES, blank=True)
    collection_centre = models.ForeignKey("core.Centre", null=True, on_delete=models.PROTECT, related_name="+")
    registered_centre = models.ForeignKey("core.Centre", null=True, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="active")
    registered_at = models.DateTimeField(default=timezone.now)
    identity_refreshed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["last_name", "first_name"]), models.Index(fields=["dob"])]
        constraints = [models.UniqueConstraint(fields=["nis_number"], condition=~models.Q(nis_number=""), name="uniq_member_nis")]

    def __str__(self):
        return f"{self.full_name} ({self.member_number})"

    @property
    def full_name(self):
        """Display name."""
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)

    def age(self, when=None):
        """Age in whole years."""
        from apps.rules.engine import age_on

        return age_on(self.dob, when or timezone.localdate())

    @property
    def current_card(self):
        """Latest non-spoiled card."""
        return self.cards.exclude(state="spoiled").order_by("-version_no", "-reprint_seq").first()


class Guardian(models.Model):
    """Parent or guardian of a minor member (BR10004)."""

    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name="guardian")
    full_name = models.CharField(max_length=120)
    relationship = models.CharField(max_length=40)
    trn = models.CharField(max_length=9, blank=True)
    trn_validated = models.BooleanField(default=False)
    phone = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.full_name} ({self.relationship})"


class MemberCondition(models.Model):
    """A certified medical condition (MR10015). Sensitive: shown only to roles that process eligibility (CS10002)."""

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="conditions")
    condition = models.ForeignKey("rules.MedicalCondition", on_delete=models.PROTECT)
    severity = models.CharField(max_length=10, choices=SEVERITIES, default="moderate")
    certified_by = models.ForeignKey("doctors.Doctor", null=True, blank=True, on_delete=models.SET_NULL)
    certified_on = models.DateField(null=True, blank=True)
    notes = EncryptedTextField(blank=True)
    active = models.BooleanField(default=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["condition__name"]

    def __str__(self):
        return f"{self.condition} ({self.severity})"


class Enrolment(models.Model):
    """When and why a member joined a programme."""

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="enrolments")
    programme = models.ForeignKey("rules.Programme", on_delete=models.PROTECT)
    enrolled_at = models.DateTimeField(default=timezone.now)
    source = models.CharField(max_length=10, choices=[("rule", "Rules engine"), ("staff", "Staff"), ("migration", "Migration")], default="rule")
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["programme__sort_order"]
        constraints = [models.UniqueConstraint(fields=["member", "programme"], condition=models.Q(ended_at__isnull=True), name="one_open_enrolment")]

    def __str__(self):
        return f"{self.member_id} in {self.programme}"


class Application(models.Model):
    """One submitted form: a new registration or a change form (MR10001–MR10014)."""

    KINDS = [("new", "New registration"), ("change", "Change form")]
    CHANNELS = [("walk_in", "Walk-in"), ("online", "Online"), ("email", "E-mail"), ("batch", "Batch (organisation)")]
    STATUSES = [
        ("draft", "In progress"),
        ("ready", "Ready to approve"),
        ("awaiting", "Awaiting approval / confirmation"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("terminated", "Terminated"),
    ]
    REPRINT_REASONS = [
        ("", "No reprint"),
        ("replacement", "Replacement (lost or damaged)"),
        ("name_change", "Name change"),
        ("dob_change", "Date-of-birth change"),
    ]
    OPEN_STATUSES = ("draft", "ready", "awaiting")

    tracking_number = models.CharField(max_length=20, unique=True, default=next_tracking_number)
    kind = models.CharField(max_length=6, choices=KINDS, default="new")
    channel = models.CharField(max_length=8, choices=CHANNELS, default="walk_in")
    centre = models.ForeignKey("core.Centre", on_delete=models.PROTECT, related_name="applications", verbose_name="processing centre")
    received_at = models.DateTimeField("date and time received", default=timezone.now)
    entered_at = models.DateTimeField(auto_now_add=True)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=STATUSES, default="draft", db_index=True)
    member = models.ForeignKey(Member, null=True, blank=True, on_delete=models.PROTECT, related_name="applications")

    # Identity
    trn = models.CharField("TRN / SRN", max_length=9, db_index=True, blank=True)
    is_srn = models.BooleanField(default=False)
    nis_number = models.CharField("NIS number", max_length=12, blank=True)
    srn_issue = models.ForeignKey("identity.SrnIssue", null=True, blank=True, on_delete=models.SET_NULL, related_name="applications")
    trn_validation = models.ForeignKey("identity.TrnValidation", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    identity_confirmed = models.BooleanField(default=False)
    form_first_name = models.CharField("first name on form", max_length=60, blank=True)
    form_last_name = models.CharField("last name on form", max_length=60, blank=True)
    form_dob = models.DateField("date of birth on form", null=True, blank=True)
    first_name = models.CharField(max_length=60, blank=True)
    middle_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDERS, blank=True)

    # Contact and collection
    phone_mobile = models.CharField("mobile", max_length=20, blank=True)
    phone_home = models.CharField("home phone", max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address_line1 = models.CharField("address", max_length=120, blank=True)
    address_line2 = models.CharField("address (line 2)", max_length=120, blank=True)
    parish = models.CharField(max_length=3, choices=PARISHES, blank=True)
    collection_centre = models.ForeignKey(
        "core.Centre", null=True, blank=True, on_delete=models.PROTECT, related_name="+", verbose_name="card collection centre"
    )

    # Guardian (minors)
    guardian_name = models.CharField("guardian's full name", max_length=120, blank=True)
    guardian_relationship = models.CharField("relationship", max_length=40, blank=True)
    guardian_trn = models.CharField("guardian's TRN", max_length=9, blank=True)
    guardian_phone = models.CharField("guardian's phone", max_length=20, blank=True)

    # Doctor
    doctor = models.ForeignKey("doctors.Doctor", null=True, blank=True, on_delete=models.SET_NULL, related_name="applications")
    doctor_mcj = models.CharField("doctor's MCJ no.", max_length=12, blank=True)
    referring_doctor_name = models.CharField(max_length=120, blank=True)

    # Change form
    change_contact = models.BooleanField(default=False)
    change_conditions = models.BooleanField(default=False)
    change_guardian = models.BooleanField(default=False)
    change_identity = models.BooleanField("refresh name/DOB from TRN service", default=False)
    reprint_reason = models.CharField(max_length=12, choices=REPRINT_REASONS, blank=True)

    # Data Protection Act 2020: consent to processing, incl. health data
    consent_given = models.BooleanField("applicant consents to the processing described in the privacy notice", default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=20, blank=True)

    # Online intake
    portal_reference = models.CharField(max_length=60, blank=True, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_applications")
    worked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    worked_heartbeat = models.DateTimeField(null=True, blank=True)

    # Decision
    rejection_reason = models.ForeignKey("rules.RejectionReason", null=True, blank=True, on_delete=models.PROTECT)
    rejection_text = models.CharField(max_length=300, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    anonymised_at = models.DateTimeField(null=True, blank=True, help_text="Personal details removed under the retention policy.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["channel", "status"]), models.Index(fields=["member", "status"])]

    def __str__(self):
        return self.tracking_number

    @property
    def is_open(self):
        """Still being processed."""
        return self.status in self.OPEN_STATUSES

    @property
    def is_online(self):
        """MR10011 / OR10005 tag."""
        return self.channel == "online"

    @property
    def applicant_name(self):
        """Best available name for lists."""
        parts = [self.first_name, self.middle_name, self.last_name] if self.last_name else [self.form_first_name, self.form_last_name]
        return " ".join(p for p in parts if p) or "—"

    def worked_by_other(self, user):
        """OR10010: someone else has the record open (heartbeat newer than the work-lock window)."""
        from apps.core.models import Parameter

        if not self.worked_by_id or self.worked_by_id == user.pk or not self.worked_heartbeat:
            return None
        window = int(Parameter.get("work-lock-seconds"))
        if (timezone.now() - self.worked_heartbeat).total_seconds() > window:
            return None
        return self.worked_by


class ApplicationCondition(models.Model):
    """Conditions as certified on the form."""

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="conditions")
    condition = models.ForeignKey("rules.MedicalCondition", on_delete=models.PROTECT)
    severity = models.CharField(max_length=10, choices=SEVERITIES, default="moderate")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["application", "condition"], name="uniq_app_condition")]

    def __str__(self):
        return str(self.condition)
