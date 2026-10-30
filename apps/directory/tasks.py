"""Nightly directory reconciliation."""

from celery import shared_task


@shared_task
def sync_directory_users():
    """Disable accounts that are gone or disabled in AD and refresh roles for the rest."""
    from .services import sync_ad_users

    return sync_ad_users()
