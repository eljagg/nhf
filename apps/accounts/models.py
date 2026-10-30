"""Staff accounts and temporary role grants (UM10002, UM10007, UM10011)."""

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.utils import timezone

from apps.core.crypto import EncryptedTextField


class User(AbstractUser):
    """A staff user. Directory-sourced accounts (AD/LDAPS, OIDC) map onto this model in Phase B."""

    centre = models.ForeignKey("core.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="staff")
    staff_number = models.CharField(max_length=20, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True, help_text="Temporary lock set by an administrator (UM10011).")
    lock_reason = models.CharField(max_length=200, blank=True)
    password_changed_at = models.DateTimeField(default=timezone.now, help_text="Drives password expiry.")
    source = models.CharField(
        max_length=8,
        choices=[("local", "Local account"), ("ad", "Active Directory"), ("entra", "Entra ID")],
        default="local",
        help_text="Where the account and its roles come from.",
    )
    external_id = models.CharField(max_length=120, blank=True, db_index=True, help_text="Directory object id (AD objectGUID / Entra oid).")
    directory_synced_at = models.DateTimeField(null=True, blank=True)

    ID_TYPES = [
        ("nids", "National ID (NIDS)"),
        ("drivers", "Driver's licence"),
        ("passport", "Passport"),
        ("staff", "NHF staff ID card"),
        ("other", "Other government ID"),
    ]
    job_title = models.CharField(max_length=80, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    photo = models.ForeignKey("core.StoredImage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    id_type = models.CharField("ID type", max_length=10, choices=ID_TYPES, blank=True)
    id_number = EncryptedTextField("ID number", blank=True, help_text="Stored encrypted.")
    id_issue_date = models.DateField("ID issue date", null=True, blank=True)
    id_expiry = models.DateField("ID expiry", null=True, blank=True)
    id_document = models.ForeignKey("core.StoredImage", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", verbose_name="ID picture")
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_until = models.DateTimeField(null=True, blank=True, help_text="Blank: until reinstated.")
    suspension_reason = models.CharField(max_length=300, blank=True)
    suspended_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    deactivated_at = models.DateTimeField(null=True, blank=True, help_text="When the account was last disabled; drives retention of staff ID records.")
    deactivated_by_directory = models.BooleanField(
        default=False, help_text="Disabled because the directory said so (re-enabled automatically if the directory enables it again)."
    )

    def save(self, *args, **kwargs):
        if not self.is_active and self.deactivated_at is None:
            self.deactivated_at = timezone.now()
        elif self.is_active and self.deactivated_at is not None:
            self.deactivated_at = None
            self.deactivated_by_directory = False
        super().save(*args, **kwargs)

    def set_password(self, raw_password):
        """Record when the password changed; the new hash is added to the password history on save."""
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()
        self._password_changed_now = True

    def display_name(self):
        """Full name or username."""
        return self.get_full_name() or self.username

    @property
    def is_suspended(self):
        """True while a suspension is in force (an end date, if set, lifts it automatically)."""
        return bool(self.suspended_at and (self.suspended_until is None or self.suspended_until > timezone.now()))

    @property
    def id_expired(self):
        return bool(self.id_expiry and self.id_expiry < timezone.localdate())

    @property
    def id_number_masked(self):
        """Last four characters only."""
        value = self.id_number or ""
        return ("•" * max(len(value) - 4, 0) + value[-4:]) if value else ""

    @property
    def is_temporarily_locked(self):
        """True while an administrator lock is in force."""
        return bool(self.locked_until and self.locked_until > timezone.now())


class TemporaryRole(models.Model):
    """A role granted for a limited period, e.g. cover for a supervisor on leave (UM10007)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="temporary_roles")
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    reason = models.CharField(max_length=200)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.user} → {self.group} until {self.expires_at:%Y-%m-%d %H:%M}"

    @property
    def is_active(self):
        """True between start and expiry unless revoked."""
        now = timezone.now()
        return self.revoked_at is None and self.starts_at <= now < self.expires_at


class RoleChangeRequest(models.Model):
    """Two-person rule for roles on local accounts: an application administrator asks, a manager (not the requester,
    not the person concerned) approves. Directory accounts get their roles from AD/Entra groups instead."""

    ACTIONS = [("add", "Add role"), ("remove", "Remove role")]
    STATUSES = [("pending", "Waiting for approval"), ("approved", "Approved and applied"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_requests")
    role = models.CharField(max_length=20)
    action = models.CharField(max_length=6, choices=ACTIONS)
    reason = models.CharField(max_length=300)
    status = models.CharField(max_length=10, choices=STATUSES, default="pending")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.get_action_display()} {self.role} for {self.target}"
