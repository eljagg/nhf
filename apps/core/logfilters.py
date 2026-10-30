"""Logging filters: split informational output from real problems."""

import logging


class BelowWarning(logging.Filter):
    """For the stdout handler: everything under WARNING."""

    def filter(self, record):
        return record.levelno < logging.WARNING


class Quiet403(logging.Filter):
    """For the stderr handler: a page refused (403) or not found (404) is normal operation, not an error.

    Those requests are already in the web server's access log and, for signed-in users, in the access log screen, so
    Django's extra warning (with a traceback for 403) is dropped instead of showing as [err] on the hosting dashboard.
    """

    def filter(self, record):
        return getattr(record, "status_code", None) not in (403, 404)
