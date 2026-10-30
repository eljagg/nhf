"""Nightly re-check of confirmed doctors and nurses against their council register."""

from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Parameter

from .models import Doctor, Nurse
from .verification import verify

BATCH = 500


@shared_task
def recheck_registers():
    """Registrations lapse each year; re-check the oldest checks first, a batch per night."""
    cutoff = timezone.now() - timedelta(days=int(Parameter.get("register-recheck-days")))
    result = {}
    for model in (Doctor, Nurse):
        due = model.objects.filter(status="confirmed").filter(Q(register_checked_at__isnull=True) | Q(register_checked_at__lt=cutoff))
        outcomes = []
        for practitioner in due.order_by("register_checked_at")[:BATCH]:
            outcomes.append(verify(practitioner))
            if outcomes[-1] == "unavailable":
                break  # that council's register is down; try again tomorrow
        result[model.__name__.lower()] = {o: outcomes.count(o) for o in set(outcomes)}
    return result
