"""Authentication backend for Active Directory (LDAPS)."""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from . import ldap
from .provisioning import NotAuthorised, provision

log = logging.getLogger(__name__)


class ActiveDirectoryBackend(ModelBackend):
    """Checks the password against AD, then creates/updates the local account and its roles from AD groups.

    Local accounts with a usable password (break-glass administrators, demo users) are left to ModelBackend.
    If the directory is unreachable the sign-in fails for directory users (no cached passwords), and local
    administrator accounts still work.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not settings.LDAP["ENABLED"] or not username:
            return None
        local = get_user_model().objects.filter(username__iexact=username, source="local").first()
        if local is not None and local.has_usable_password():
            return None
        try:
            identity = ldap.authenticate(username, password)
        except ldap.DirectoryError as exc:
            log.warning("directory sign-in unavailable: %s", exc)
            if request is not None:
                request.directory_error = "The NHF directory could not be reached. Try again shortly, or contact the ICT service desk."
            return None
        if identity is None:
            return None
        try:
            user = provision(identity)
        except NotAuthorised as exc:
            if request is not None:
                request.directory_error = str(exc)
            return None
        return user if self.user_can_authenticate(user) else None
