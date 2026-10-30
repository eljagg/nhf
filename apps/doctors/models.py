"""NHF Doctors and Nurses registers (DV10001–DV10005) and the local copy of the council registers."""

from django.conf import settings
from django.db import models

from apps.core.models import PARISHES

COUNCILS = [("mcj", "Medical Council of Jamaica"), ("ncj", "Nursing Council of Jamaica")]
REGISTER_STATUSES = [
    ("", "Not checked"),
    ("active", "Registered — in good standing"),
    ("lapsed", "Registration lapsed (not renewed)"),
    ("suspended", "Suspended"),
    ("removed", "Removed from the register"),
    ("not_found", "Not on the register"),
]


class PractitionerProfile(models.Model):
    """Fields shared by doctors and nurses: practice location, photo, and the last council register check."""

    practice_name = models.CharField("practice / workplace", max_length=120, blank=True)
    address_line1 = models.CharField("practice address", max_length=120, blank=True)
    address_line2 = models.CharField("address line 2", max_length=120, blank=True)
    town = models.CharField("town / district", max_length=60, blank=True)
    parish = models.CharField(max_length=3, choices=PARISHES, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    photo = models.ForeignKey("core.StoredImage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    register_status = models.CharField(max_length=10, choices=REGISTER_STATUSES, blank=True, default="")
    register_checked_at = models.DateTimeField(null=True, blank=True)
    licence_valid_until = models.DateField(null=True, blank=True)
    verified_via = models.CharField(
        max_length=10,
        blank=True,
        choices=[("manual", "Confirmed by NHF staff"), ("register", "Council register")],
        help_text="How the registration was confirmed.",
    )

    class Meta:
        abstract = True

    @property
    def full_address(self):
        """One line, for lists and print."""
        return ", ".join(p for p in [self.address_line1, self.address_line2, self.town, self.get_parish_display()] if p)

    @property
    def register_concern(self):
        """True when the council register no longer shows the person in good standing."""
        return self.register_status in ("lapsed", "suspended", "removed", "not_found") and self.status == "confirmed"


class Doctor(PractitionerProfile):
    """A medical practitioner identified by Medical Council of Jamaica registration number."""

    council = "mcj"
    STATUSES = [("confirmed", "Confirmed"), ("pending", "Awaiting MCJ confirmation"), ("rejected", "Not confirmed by MCJ")]
    mcj_number = models.CharField("MCJ registration no.", max_length=12, unique=True)
    title = models.CharField(max_length=10, default="Dr")
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    specialty = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="confirmed")
    source = models.CharField(max_length=20, default="register")  # register | application | portal | staff
    confirmed_with_mcj_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        name = " ".join(p for p in [self.title, self.first_name, self.last_name] if p) if self.last_name else "Unknown doctor"
        return f"{name} (MCJ {self.mcj_number})"

    @property
    def number(self):
        return self.mcj_number


class Nurse(PractitionerProfile):
    """A nurse or midwife identified by Nursing Council of Jamaica registration number."""

    council = "ncj"
    CATEGORIES = [
        ("rn", "Registered Nurse"),
        ("rm", "Registered Midwife"),
        ("rnrm", "Registered Nurse and Midwife"),
        ("np", "Nurse Practitioner"),
        ("ean", "Enrolled Assistant Nurse"),
        ("phn", "Public Health Nurse"),
        ("crna", "Nurse Anaesthetist"),
    ]
    STATUSES = [("confirmed", "Confirmed"), ("pending", "Awaiting NCJ confirmation"), ("rejected", "Not confirmed by NCJ")]
    ncj_number = models.CharField("NCJ registration no.", max_length=12, unique=True)
    title = models.CharField(max_length=10, default="Nurse")
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    category = models.CharField(max_length=5, choices=CATEGORIES, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    confirmed_with_ncj_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        name = " ".join(p for p in [self.title, self.first_name, self.last_name] if p) if self.last_name else "Unknown nurse"
        return f"{name} (NCJ {self.ncj_number})"

    @property
    def number(self):
        return self.ncj_number

    @property
    def specialty(self):
        return self.get_category_display()


class CouncilRegisterEntry(models.Model):
    """Local copy of a council register row: imported from the file the council supplies (or synthetic in the demo).

    The 'local' register adapter checks numbers against these rows; the 'https' adapter asks the council's service instead.
    """

    council = models.CharField(max_length=3, choices=COUNCILS)
    number = models.CharField(max_length=12)
    title = models.CharField(max_length=10, blank=True)
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    specialty = models.CharField("specialty / category", max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=[s for s in REGISTER_STATUSES if s[0] not in ("", "not_found")], default="active")
    valid_until = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=10, default="file")  # file | demo
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["council", "number"]
        constraints = [models.UniqueConstraint(fields=["council", "number"], name="uniq_council_number")]

    def __str__(self):
        return f"{self.council.upper()} {self.number} {self.first_name} {self.last_name} ({self.status})"
