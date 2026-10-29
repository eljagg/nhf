"""Writing the interaction log."""

from apps.core.audit import current_user

from .models import Interaction


def log(summary, *, member=None, application=None, kind="system", event="", actor=None, centre=None):
    """Append one interaction. Member is taken from the application when not given."""
    if member is None and application is not None:
        member = application.member
    actor = actor or current_user()
    if centre is None:
        centre = getattr(actor, "centre", None) or (application.centre if application else None)
    return Interaction.objects.create(member=member, application=application, kind=kind, event=event, summary=summary[:400], actor=actor, centre=centre)
