"""Scheduled retention sweep."""

from celery import shared_task


@shared_task
def retention_sweep():
    """Daily: apply the retention rules."""
    from .services import run_retention

    run_retention()
