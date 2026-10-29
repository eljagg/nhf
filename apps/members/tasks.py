"""Scheduled member jobs."""

from celery import shared_task
from django.utils import timezone


@shared_task
def jadep_sweep():
    """BR10005: members who reached the JADEP age since they registered are enrolled automatically."""
    from apps.core.models import Parameter
    from apps.interactions.services import log
    from apps.rules.models import Programme

    from .models import Enrolment, Member

    jadep = Programme.objects.filter(code="jadep", is_active=True).first()
    if jadep is None:
        return 0
    age = int(Parameter.get("jadep-age"))
    today = timezone.localdate()
    cutoff = today.replace(year=today.year - age)
    count = 0
    for member in Member.objects.filter(status="active", dob__lte=cutoff).exclude(enrolments__programme=jadep, enrolments__ended_at__isnull=True)[:5000]:
        if not member.conditions.filter(active=True, condition__programmes=jadep).exists():
            continue
        Enrolment.objects.create(member=member, programme=jadep, source="rule")
        log(f"Enrolled in JADEP automatically at age {member.age()}", member=member, event="enrolment.jadep")
        count += 1
    return count
