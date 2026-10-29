"""Card housekeeping."""

from celery import shared_task


@shared_task
def daily_queue_reset():
    """CP10005: the counter print queue shows today's work; older unprinted cards move to the back-office queue view.

    Phase A records the reset; the queue view itself filters on the current day.
    """
    from apps.core import audit

    audit.record("cards.queue_reset", None, "Daily print-queue reset")
