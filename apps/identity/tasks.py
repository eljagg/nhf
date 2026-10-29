"""Identity worker queue."""

from celery import shared_task


@shared_task(bind=True, max_retries=0)
def run_trn_validation(self, validation_id):
    """Call the TRN service for one validation."""
    from .services import perform_validation

    perform_validation(validation_id)
