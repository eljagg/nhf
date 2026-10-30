"""Online queue and the doctor-portal simulator (demo)."""

import random

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.roles import PROCESS_ROLES, has_role, role_required
from apps.doctors.models import Doctor
from apps.identity.models import TajIdentity
from apps.members.models import Application, Member

from . import services


@role_required(*PROCESS_ROLES)
def queue(request):
    """OR10004–OR10010: the online applications area."""
    qs = (
        Application.objects.filter(channel="online", status__in=Application.OPEN_STATUSES)
        .select_related("assigned_to", "worked_by", "doctor", "member")
        .order_by("received_at")
    )
    from apps.accounts.scoping import scope_by_centre

    qs = scope_by_centre(qs, request.user)
    if request.GET.get("mine"):
        qs = qs.filter(assigned_to=request.user)
    rows = [{"a": a, "locked_by": a.worked_by_other(request.user)} for a in qs]
    agents = get_user_model().objects.filter(is_active=True, groups__name="customer_care").distinct().order_by("first_name")
    return render(
        request,
        "intake/queue.html",
        {
            "rows": rows,
            "agents": agents,
            "can_assign": has_role(request.user, "supervisor", "manager"),
            "demo": settings.DEMO_MODE,
            "page_title": "Online Intake",
        },
    )


@require_POST
@role_required(*PROCESS_ROLES)
def simulate(request):
    """Demo only: post a synthetic submission exactly as the doctor portal would."""
    if not settings.DEMO_MODE:
        raise PermissionDenied
    rng = random.SystemRandom()
    kind = request.POST.get("kind", "new")
    if kind == "change":
        person = Member.objects.order_by("?").first()
        patient = {
            "trn": person.trn,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "dob": person.dob.isoformat(),
            "mobile": person.phone_mobile,
        }
    else:
        person = (
            TajIdentity.objects.filter(demo_note="")
            .exclude(trn__in=Member.objects.values("trn"))
            .exclude(trn__in=Application.objects.values("trn"))
            .order_by("?")
            .first()
        )
        patient = {
            "trn": person.trn,
            "first_name": person.first_name,
            "last_name": person.last_name,
            "dob": person.dob.isoformat(),
            "mobile": f"876-{rng.randint(300, 899)}-{rng.randint(1000, 9999)}",
        }
    doctor = Doctor.objects.filter(status="confirmed").order_by("?").first()
    app = services.receive_portal_submission(
        {
            "reference": f"DP-SIM-{timezone.now():%y%m%d%H%M%S}-{rng.randint(100, 999)}",
            "kind": kind,
            "patient": patient,
            "doctor": {"mcj_number": doctor.mcj_number, "name": f"Dr {doctor.first_name} {doctor.last_name}"},
            "conditions": [rng.choice(["hypertension", "diabetes", "asthma", "glaucoma", "arthritis"])],
            "consent": True,
        }
    )
    messages.success(request, f"Portal submission received as {app.tracking_number} ({app.get_kind_display().lower()}).")
    return redirect("intake:queue")
