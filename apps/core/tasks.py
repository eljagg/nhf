"""Notification dispatch. Phase A: SMS is recorded as a preview (no gateway yet); e-mail goes through Django's backend."""

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


@shared_task
def send_notification(notification_id):
    """Send one queued notification through its channel adapter."""
    from .models import IntegrationRun, Notification

    note = Notification.objects.filter(pk=notification_id, status="queued").first()
    if note is None:
        return
    if note.channel == "email" and note.to:
        send_mail(note.subject, note.body, settings.DEFAULT_FROM_EMAIL, [note.to], fail_silently=True)
        note.status = "sent"
    elif note.channel == "sms":
        IntegrationRun.objects.create(system="sms", operation="send", adapter="preview", reference=note.to, message=note.body[:300])
        note.status = "previewed"
    else:
        note.status = "sent"
    note.sent_at = timezone.now()
    note.save(update_fields=["status", "sent_at"])


@shared_task
def check_id_expiry():
    """Daily: tell staff and supervisors about expired or soon-to-expire IDs."""
    from .idexpiry import check_id_expiry as run

    return run()
