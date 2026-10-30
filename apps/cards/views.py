"""Print queue (Phase A view; printing, verification and dispatch screens arrive in sprint A2)."""

from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.roles import role_required

from .models import Card


@role_required("customer_care", "supervisor", "manager", "print_operator")
def queue(request):
    """CP10003: only cards flagged for printing; the centre's queue by default."""
    qs = Card.objects.filter(state="queued").select_related("member", "centre")
    from apps.accounts.scoping import sees_all_centres

    if not sees_all_centres(request.user):
        qs = qs.filter(centre=request.user.centre)  # centre-bound staff print their own centre's cards only
    elif request.GET.get("centre") and request.GET["centre"] != "all":
        qs = qs.filter(centre_id=request.GET["centre"])
    page = Paginator(qs.order_by("queued_at"), 50).get_page(request.GET.get("page"))
    return render(request, "cards/queue.html", {"page": page, "page_title": "Print queue"})
