"""Card lifecycle: queued → printed → verified → dispatched, or spoiled (CP, CV, CD requirement groups)."""

import re
import unicodedata

from django.conf import settings
from django.db import models
from django.utils import timezone


def clean_card_name(value):
    """CP10007: printable name — accents folded, special characters removed, upper case."""
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z \-]", "", value.upper()).strip()


class Card(models.Model):
    """One physical card. version_no increments on reprint (BR10007); a spoil override keeps it (CP10004)."""

    STATES = [("queued", "Queued for printing"), ("printed", "Printed"), ("verified", "Verified"), ("dispatched", "Dispatched"), ("spoiled", "Spoiled")]
    REASONS = [
        ("new", "New member"),
        ("replacement", "Replacement"),
        ("name_change", "Name change"),
        ("dob_change", "Date-of-birth change"),
        ("spoil", "Spoil reprint"),
    ]
    member = models.ForeignKey("members.Member", on_delete=models.PROTECT, related_name="cards")
    application = models.ForeignKey("members.Application", null=True, blank=True, on_delete=models.SET_NULL, related_name="cards")
    version_no = models.PositiveSmallIntegerField(default=1)
    reprint_seq = models.PositiveSmallIntegerField(default=0, help_text="Spoil reprints of the same version.")
    reason = models.CharField(max_length=12, choices=REASONS, default="new")
    state = models.CharField(max_length=10, choices=STATES, default="queued", db_index=True)
    centre = models.ForeignKey("core.Centre", null=True, on_delete=models.PROTECT, related_name="+", verbose_name="print/collection centre")
    print_name = models.CharField(max_length=60)
    track1 = models.CharField(max_length=79, blank=True)
    track2 = models.CharField(max_length=40, blank=True)
    phi_reconciled_at = models.DateTimeField(null=True, blank=True)
    serial_number = models.CharField(max_length=30, blank=True, db_index=True)
    queued_at = models.DateTimeField(default=timezone.now)
    printed_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    spoiled_at = models.DateTimeField(null=True, blank=True)
    spoil_reason = models.CharField(max_length=200, blank=True)
    queued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-queued_at"]
        constraints = [models.UniqueConstraint(fields=["member", "version_no", "reprint_seq"], name="uniq_card_version")]

    def __str__(self):
        return f"Card v{self.version_no} for {self.member_id} ({self.state})"

    def encode_tracks(self):
        """ISO 7811 Track 1 (alphanumeric) and Track 2 (numeric) strings so ID Works only maps fields."""
        m = self.member
        surname, given = clean_card_name(m.last_name), clean_card_name(f"{m.first_name} {m.middle_name}".strip())
        self.track1 = f"%B{m.member_number}^{surname}/{given}^{self.version_no:02d}{m.dob:%Y%m%d}?"[:79]
        self.track2 = f";{m.member_number}={self.version_no:02d}{m.dob:%y%m%d}?"
