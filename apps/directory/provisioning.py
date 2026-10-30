"""Create or update a local account from a directory identity, and apply group → role / centre mappings."""

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.accounts.roles import ROLES
from apps.core import audit

from .models import GroupMapping


class NotAuthorised(Exception):
    """The person is in the directory but in no group mapped to a role in this system."""


@dataclass
class DirectoryIdentity:
    """What a directory says about a person."""

    source: str  # ad | entra
    username: str
    external_id: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    groups: list = field(default_factory=list)
    enabled: bool = True


def mapped_roles_and_centre(source, groups):
    """Roles and (first) centre for a set of directory groups, case-insensitive."""
    wanted = {g.lower() for g in groups}
    roles, centre = set(), None
    for m in GroupMapping.objects.filter(source=source).select_related("centre"):
        if m.group.lower() in wanted:
            if m.role:
                roles.add(m.role)
            if m.centre_id and centre is None:
                centre = m.centre
    return roles, centre


def provision(identity: DirectoryIdentity):
    """Find or create the account, refresh its details and roles from the directory. Raises NotAuthorised when no role is mapped."""
    user_model = get_user_model()
    if not identity.enabled:
        user_model.objects.filter(source=identity.source, username__iexact=identity.username, is_active=True).update(
            is_active=False, deactivated_at=timezone.now(), deactivated_by_directory=True
        )
        raise NotAuthorised("This account is disabled in the directory.")
    roles, centre = mapped_roles_and_centre(identity.source, identity.groups)
    if not roles:
        raise NotAuthorised("Your directory account is not in any group that gives access to this system. Ask the application administrator.")
    user = user_model.objects.filter(source=identity.source, external_id=identity.external_id).first() if identity.external_id else None
    if user is None:
        user = user_model.objects.filter(username__iexact=identity.username).first()
        if user is not None and user.source == "local" and user.has_usable_password():
            # Never take over a local (break-glass or demo) account just because a directory name matches it.
            raise NotAuthorised("A local account with this username already exists. Ask the application administrator to link or rename it.")
    if user is not None and not user.is_active and not user.deactivated_by_directory:
        # Disabled here by an administrator: a directory sign-in must not quietly switch it back on.
        raise NotAuthorised("This account has been disabled in the Member Registration System. Contact the application administrator.")
    created = user is None
    if created:
        user = user_model(username=identity.username.lower(), source=identity.source)
        user.set_unusable_password()
    before = set(user.groups.values_list("name", flat=True)) if not created else set()
    user.source = identity.source
    user.external_id = identity.external_id or user.external_id
    user.first_name = identity.first_name[:150] or user.first_name
    user.last_name = identity.last_name[:150] or user.last_name
    user.email = identity.email or user.email
    if centre is not None:
        user.centre = centre
    user.is_active = True
    user.deactivated_at = None
    user.deactivated_by_directory = False
    user.is_staff = bool(roles & {"back_office", "ict_admin", "auditor", "dpo"})
    user.directory_synced_at = timezone.now()
    user.save()
    user.groups.set(Group.objects.filter(name__in=roles))
    if created:
        audit.record("directory.user_created", user, f"{user.username} created from {user.get_source_display()} with roles {sorted(roles)}", actor=user)
    elif before != roles:
        audit.record(
            "directory.roles_changed",
            user,
            f"{user.username}: roles from {user.get_source_display()} changed {sorted(before)} → {sorted(roles)}",
            actor=user,
            added=sorted(roles - before),
            removed=sorted(before - roles),
        )
    return user


def role_label(code):
    """Readable role name."""
    return ROLES.get(code, (code,))[0]
