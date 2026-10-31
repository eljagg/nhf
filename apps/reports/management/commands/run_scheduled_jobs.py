"""Run the report e-mails and overdue-work escalation once.

On NHF's servers Celery beat runs these every 15 minutes / hourly. On a host with no beat process (the Railway
demonstration), schedule this command instead, e.g. a Railway cron service: `python manage.py run_scheduled_jobs`
every 15 minutes.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send due scheduled reports and escalate overdue work (NT10002, NT10003)."

    def handle(self, *args, **opts):
        from apps.reports.escalation import run as escalate
        from apps.reports.scheduling import run_due

        sent = run_due()
        told = escalate()
        self.stdout.write(f"reports: {len(sent)} schedule(s) sent; escalations: {told}")
