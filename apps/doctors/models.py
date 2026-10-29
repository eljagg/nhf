"""NHF Doctors register (DV10001–DV10005)."""

from django.conf import settings
from django.db import models

from apps.core.models import PARISHES


class Doctor(models.Model):
    """A medical practitioner identified by Medical Council of Jamaica registration number."""

    STATUSES = [("confirmed", "Confirmed"), ("pending", "Awaiting MCJ confirmation"), ("rejected", "Not confirmed by MCJ")]
    mcj_number = models.CharField("MCJ registration no.", max_length=12, unique=True)
    title = models.CharField(max_length=10, default="Dr")
    first_name = models.CharField(max_length=60, blank=True)
    last_name = models.CharField(max_length=60, blank=True)
    specialty = models.CharField(max_length=80, blank=True)
    practice_name = models.CharField(max_length=120, blank=True)
    parish = models.CharField(max_length=3, choices=PARISHES, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default="confirmed")
    source = models.CharField(max_length=20, default="register")  # register | application | portal
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
