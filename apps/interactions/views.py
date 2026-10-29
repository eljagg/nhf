"""Append a note to an interaction (IL10002)."""

from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.accounts.roles import PROCESS_ROLES, role_required
from apps.core import audit

from .models import Interaction, InteractionNote


@require_POST
@role_required(*PROCESS_ROLES)
def add_note(request, pk):
    """Add information to an interaction after it was entered; the original entry is never changed."""
    interaction = get_object_or_404(Interaction, pk=pk)
    body = request.POST.get("body", "").strip()[:2000]
    if body:
        note = InteractionNote.objects.create(interaction=interaction, author=request.user, body=body)
        audit.record("interaction.note_added", interaction, f"Note added to interaction {interaction.pk}", note=note.pk)
    if interaction.application_id:
        return redirect(f"/members/applications/{interaction.application.tracking_number}/#log")
    return redirect(f"/members/{interaction.member.member_number}/#log")
