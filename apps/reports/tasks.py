"""Hourly jobs: scheduled report e-mails (NT10002) and escalation of overdue work (NT10003)."""

from celery import shared_task


@shared_task
def send_due_reports():
    from .scheduling import run_due

    return run_due()


@shared_task
def escalate_overdue():
    from .escalation import run

    return run()
