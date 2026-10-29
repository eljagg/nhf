"""Interaction log (IL10001–IL10002): every touch on a member or application; notes are append-only."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Interaction(models.Model):
    """A system event or a staff contact."""

    KINDS = [("system", "System event"), ("visit", "Counter visit"), ("call", "Telephone call"), ("email", "E-mail"), ("note", "Note"), ("sms", "SMS")]
    at = models.DateTimeField(default=timezone.now, db_index=True)
    member = models.ForeignKey("members.Member", null=True, blank=True, on_delete=models.CASCADE, related_name="interactions")
    application = models.ForeignKey("members.Application", null=True, blank=True, on_delete=models.CASCADE, related_name="interactions")
    kind = models.CharField(max_length=8, choices=KINDS, default="system")
    event = models.CharField(max_length=60, blank=True, db_index=True)
    summary = models.CharField(max_length=400)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    centre = models.ForeignKey("core.Centre", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        return self.summary

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Interactions are append-only; add a note instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Interactions cannot be deleted.")


class InteractionNote(models.Model):
    """IL10002: information added to an interaction after entry. Append-only."""

    interaction = models.ForeignKey(Interaction, on_delete=models.CASCADE, related_name="notes")
    at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    body = models.TextField(max_length=2000)

    class Meta:
        ordering = ["at"]

    def __str__(self):
        return self.body[:60]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Notes are append-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Notes cannot be deleted.")
