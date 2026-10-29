"""Doctor validation and MCJ confirmation workflow."""

import re

from django.utils import timezone

from apps.core import audit
from apps.core.notifications import notify_role

from .models import Doctor


def clean_mcj(value):
    """Upper-case alphanumerics."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def resolve(mcj_number, *, tracking="", name_hint="", user=None, source="application"):
    """DV10001–DV10003: find the doctor; an unknown number creates a pending entry and a confirmation task."""
    mcj = clean_mcj(mcj_number)
    if not mcj:
        return None
    doctor = Doctor.objects.filter(mcj_number=mcj).first()
    if doctor:
        return doctor
    first, _, last = (name_hint or "").replace("Dr.", "").replace("Dr ", "").strip().rpartition(" ")
    doctor = Doctor.objects.create(mcj_number=mcj, first_name=first, last_name=last, status="pending", source=source)
    audit.record("doctor.unknown", doctor, f"MCJ {mcj} not in register; sent for confirmation", actor=user)
    notify_role("mcj_confirmer", "doctor-confirmation-needed", obj=doctor, link="/doctors/confirmations/", mcj=mcj, tracking=tracking or "—")
    return doctor


def confirm(doctor, *, user, note="", **details):
    """MCJ confirmed the registration: the doctor joins the register."""
    for key, value in details.items():
        if value:
            setattr(doctor, key, value)
    doctor.status = "confirmed"
    doctor.confirmed_with_mcj_at = timezone.now()
    doctor.confirmed_by = user
    doctor.decision_note = note
    doctor.save()
    audit.record("doctor.confirmed", doctor, f"{doctor} confirmed with MCJ", actor=user)
    return doctor


def reject(doctor, *, user, note):
    """DV10004: MCJ cannot confirm; applications naming this doctor are rejected with DOCTOR_UNCONFIRMED."""
    doctor.status = "rejected"
    doctor.confirmed_by = user
    doctor.decision_note = note
    doctor.save()
    audit.record("doctor.rejected", doctor, f"MCJ {doctor.mcj_number} not confirmed: {note}", actor=user)
    from apps.members.services import reject_for_unconfirmed_doctor

    return reject_for_unconfirmed_doctor(doctor, user=user)
