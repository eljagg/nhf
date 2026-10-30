"""Mapping directory groups (Active Directory / Entra ID) to platform roles and centres."""

from django.db import models

from apps.accounts.roles import ROLES


class GroupMapping(models.Model):
    """A directory group whose members get a role and/or a centre here. Roles are refreshed from the directory at every sign-in."""

    SOURCES = [("ad", "Active Directory group (name)"), ("entra", "Entra ID group (object id or name)")]
    source = models.CharField(max_length=6, choices=SOURCES, default="ad")
    group = models.CharField(max_length=200, help_text="AD: the group's name (CN), e.g. NHF-MRS-CustomerCare. Entra ID: the group's object id.")
    role = models.CharField(max_length=20, choices=[(k, v[0]) for k, v in ROLES.items()], blank=True)
    centre = models.ForeignKey("core.Centre", null=True, blank=True, on_delete=models.SET_NULL, help_text="Members of this group work at this centre.")
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["source", "group"]
        constraints = [models.UniqueConstraint(fields=["source", "group", "role"], name="uniq_group_mapping")]

    def __str__(self):
        target = ROLES[self.role][0] if self.role else ""
        if self.centre_id:
            target = f"{target} @ {self.centre}" if target else str(self.centre)
        return f"{self.group} → {target or '—'}"
