"""Print queue (Phase A view; printing, verification and dispatch screens arrive in sprint A2)."""

from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.roles import has_role, role_required

from .models import Card


@role_required("customer_care", "supervisor", "manager", "print_operator")
def queue(request):
    """CP10003: only cards flagged for printing; the centre's queue by default."""
    qs = Card.objects.filter(state="queued").select_related("member", "centre")
    centre = request.GET.get("centre")
    if centre != "all" and request.user.centre_id and not has_role(request.user, "manager"):
        qs = qs.filter(centre=request.user.centre)
    page = Paginator(qs.order_by("queued_at"), 50).get_page(request.GET.get("page"))
    return render(request, "cards/queue.html", {"page": page, "page_title": "Print queue"})
