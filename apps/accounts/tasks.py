"""Housekeeping for role grants."""

from celery import shared_task
from django.utils import timezone

from apps.core import audit


@shared_task
def expire_temporary_roles():
    """Record expiry of temporary grants in the audit trail (access stops at expires_at regardless)."""
    from .models import TemporaryRole

    for grant in TemporaryRole.objects.filter(revoked_at__isnull=True, expires_at__lte=timezone.now()):
        grant.revoked_at = grant.expires_at
        grant.save(update_fields=["revoked_at"])
        audit.record("role.temporary_expired", grant.user, f"{grant.group.name} expired for {grant.user}")
