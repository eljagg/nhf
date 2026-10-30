"""v0.2.2: practice address and photo, nurses, council register connector, staff photo / ID / suspension."""

import io
from datetime import date, timedelta
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from apps.core.crypto import decrypt_bytes
from apps.core.models import AuditEvent, IntegrationRun, Notification, StoredImage
from apps.doctors import services as doctor_services
from apps.doctors.models import CouncilRegisterEntry, Doctor, Nurse
from apps.doctors.registers import HttpsRegisterAdapter
from apps.doctors.tasks import recheck_registers
from apps.doctors.verification import verify
from apps.members import services
from apps.security.models import UserSession

from .conftest import PASSWORD, make_user
from .test_counter_journey import start

pytestmark = pytest.mark.django_db


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def login_verified(client, user):
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    login(client, user)
    code = f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"
    assert client.post("/accounts/mfa/verify/", {"token": code}).status_code == 302


def jpeg(w=800, h=600, exif_gps=True, fmt="JPEG"):
    img = Image.new("RGB", (w, h), (20, 120, 90))
    buf = io.BytesIO()
    kwargs = {}
    if exif_gps and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x010F] = "SecretCam"  # Make
        exif[0x8825] = {2: (18.0, 0.0, 0.0)}  # GPS latitude
        kwargs["exif"] = exif.tobytes()
    img.save(buf, fmt, **kwargs)
    return SimpleUploadedFile(f"x.{fmt.lower()}", buf.getvalue(), content_type=f"image/{fmt.lower()}")


def mcj(number, status="active", valid=date(2027, 12, 31), **kw):
    return CouncilRegisterEntry.objects.create(
        council="mcj", number=number, first_name=kw.get("first", "Natalie"), last_name=kw.get("last", "Grant"), status=status, valid_until=valid
    )


def ncj(number, status="active", valid=date(2027, 6, 30)):
    return CouncilRegisterEntry.objects.create(
        council="ncj", number=number, first_name="Kadian", last_name="Ferguson", specialty="Registered Nurse", status=status, valid_until=valid
    )


# --- 1. Council register connector --------------------------------------------
def test_unknown_doctor_on_the_mcj_register_is_confirmed_automatically(agent, taj, run_commits):
    mcj("20015", first="Natalie", last="Grant-Wright")
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor_mcj = "20015"
    services.resolve_doctor(app, user=agent)
    doctor = Doctor.objects.get(mcj_number="20015")
    assert doctor.status == "confirmed" and doctor.verified_via == "register"
    assert doctor.last_name == "Grant-Wright" and doctor.register_status == "active"
    assert not Notification.objects.filter(template="doctor-confirmation-needed").exists()
    assert IntegrationRun.objects.filter(system="mcj", operation="verify", ok=True).exists()


def test_suspended_doctor_is_not_auto_confirmed_and_goes_to_the_queue(agent, manager, taj, run_commits):
    mcj("20022", status="suspended")
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor_mcj = "20022"
    services.resolve_doctor(app, user=agent)
    doctor = Doctor.objects.get(mcj_number="20022")
    assert doctor.status == "pending" and doctor.register_status == "suspended"
    assert Notification.objects.filter(template="doctor-confirmation-needed", body__contains="Suspended").exists()


def test_active_flag_past_its_expiry_counts_as_lapsed(agent):
    mcj("20029", status="active", valid=date.today() - timedelta(days=1))
    doctor = Doctor.objects.create(mcj_number="20029", status="pending")
    assert verify(doctor) == "still_pending"
    assert doctor.register_status == "lapsed"


def test_number_not_on_register_stays_pending(agent):
    doctor = doctor_services.resolve("99901", user=agent)
    assert doctor.status == "pending" and doctor.register_status == "not_found"


def test_register_outage_leaves_doctor_pending_and_opens_circuit(agent):
    from django.core.cache import cache

    cache.clear()
    regs = {c: {"MODE": "local", "URL": "", "API_KEY": "", "API_KEY_HEADER": "X", "TIMEOUT": 1, "SIMULATE_DOWN": True} for c in ("mcj", "ncj")}
    with override_settings(PRACTITIONER_REGISTERS=regs):
        for n in ("91001", "91002", "91003", "91004"):
            assert doctor_services.resolve(n, user=agent).status == "pending"
    assert IntegrationRun.objects.filter(system="mcj", message="circuit open").exists()
    assert Doctor.objects.get(mcj_number="91001").register_checked_at is None
    cache.clear()


def test_confirmed_doctor_later_suspended_is_flagged_on_recheck_and_applications_warn(agent, manager, doctor, taj, run_commits):
    mcj(doctor.mcj_number, status="active")
    verify(doctor)
    CouncilRegisterEntry.objects.filter(number=doctor.mcj_number).update(status="suspended")
    Doctor.objects.filter(pk=doctor.pk).update(register_checked_at=timezone.now() - timedelta(days=40))
    result = recheck_registers()
    doctor.refresh_from_db()
    assert result["doctor"].get("concern") == 1
    assert doctor.status == "confirmed" and doctor.register_concern
    assert Notification.objects.filter(template="practitioner-register-changed").exists()
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor = doctor
    app.doctor_mcj = doctor.mcj_number
    app.save()
    findings = services.evaluate(app).findings
    assert any("Suspended" in f.message for f in findings)


def test_https_adapter_reads_council_json(settings):
    settings.PRACTITIONER_REGISTERS = {
        **settings.PRACTITIONER_REGISTERS,
        "mcj": {
            "MODE": "https",
            "URL": "https://register.example/api/{number}",
            "API_KEY": "k",
            "API_KEY_HEADER": "X-API-Key",
            "TIMEOUT": 3,
            "SIMULATE_DOWN": False,
        },
    }
    ok = mock.Mock(status_code=200)
    ok.json.return_value = {"data": {"firstName": "Ann", "surname": "Lee", "status": "Struck off", "expiryDate": "2027-01-31"}}
    with mock.patch("apps.doctors.registers.requests.get", return_value=ok) as get:
        r = HttpsRegisterAdapter("mcj").lookup("12345")
    assert get.call_args.args[0] == "https://register.example/api/12345" and get.call_args.kwargs["headers"]["X-API-Key"] == "k"
    assert r.found and r.status == "removed" and r.last_name == "Lee" and r.valid_until == date(2027, 1, 31)
    with mock.patch("apps.doctors.registers.requests.get", return_value=mock.Mock(status_code=404)):
        assert not HttpsRegisterAdapter("mcj").lookup("99999").found


def test_https_adapter_refuses_plain_http(settings):
    from apps.doctors.registers import RegisterUnavailable

    settings.PRACTITIONER_REGISTERS = {
        **settings.PRACTITIONER_REGISTERS,
        "ncj": {**settings.PRACTITIONER_REGISTERS["ncj"], "MODE": "https", "URL": "http://x/{number}"},
    }
    with pytest.raises(RegisterUnavailable):
        HttpsRegisterAdapter("ncj").lookup("1")


def test_register_import_preview_then_import(client, manager):
    login_verified(client, manager)
    csv_text = "Registration Number,Title,First Name,Last Name,Specialty,Status,Valid Until\n20101,Dr,Ann,Lee,Paediatrics,Registered,2027-12-31\n20102,Dr,Bob,Ray,GP,Struck off,2026-01-31\n"
    upload = lambda: SimpleUploadedFile("mcj.csv", csv_text.encode(), content_type="text/csv")  # noqa: E731
    resp = client.post("/doctors/register-import/", {"council": "mcj", "file": upload()})
    assert resp.status_code == 200 and resp.context["preview"]["count"] == 2 and not CouncilRegisterEntry.objects.exists()
    client.post("/doctors/register-import/", {"council": "mcj", "file": upload(), "confirm": "1"})
    assert CouncilRegisterEntry.objects.get(number="20101").status == "active"
    assert CouncilRegisterEntry.objects.get(number="20102").status == "removed"
    assert AuditEvent.objects.filter(action="register.imported").exists()


def test_register_import_rejects_bad_dates(client, manager):
    login_verified(client, manager)
    f = SimpleUploadedFile("x.csv", b"registration_number,valid_until\n1,31/12/2027\n", content_type="text/csv")
    resp = client.post("/doctors/register-import/", {"council": "ncj", "file": f, "confirm": "1"})
    assert resp.context["preview"]["error_count"] == 1 and not CouncilRegisterEntry.objects.exists()


# --- 2. Doctors: address, photo, re-check ----------------------------------------
def test_doctor_practice_address_saved_and_shown(client, agent, doctor):
    login(client, agent)
    data = {
        "title": "Dr",
        "first_name": "Kevin",
        "last_name": "Spence",
        "specialty": "GP",
        "practice_name": "Spence Medical",
        "address_line1": "12 Hope Road",
        "address_line2": "Suite 3",
        "town": "Liguanea",
        "parish": "AND",
        "phone": "",
        "email": "",
    }
    assert client.post(f"/doctors/{doctor.mcj_number}/", data).status_code == 302
    doctor.refresh_from_db()
    assert doctor.full_address == "12 Hope Road, Suite 3, Liguanea, St Andrew"
    assert "12 Hope Road" in client.get("/doctors/?q=Liguanea").content.decode()


def test_doctor_photo_is_reencoded_without_exif_and_encrypted(client, agent, doctor):
    login(client, agent)
    client.post(f"/doctors/doctor/{doctor.mcj_number}/photo/", {"photo": jpeg(1600, 1200)})
    doctor.refresh_from_db()
    img = doctor.photo
    assert img and img.kind == "practitioner_photo" and max(img.width, img.height) == 512
    assert b"SecretCam" not in decrypt_bytes(img.data) and not img.data.startswith("\xff")
    reloaded = Image.open(io.BytesIO(decrypt_bytes(img.data)))
    assert not reloaded.getexif()
    resp = client.get(f"/images/{img.pk}/")
    assert resp.status_code == 200 and resp["Content-Type"] == "image/jpeg"


def test_replacing_a_photo_deletes_the_old_image(client, agent, doctor):
    login(client, agent)
    client.post(f"/doctors/doctor/{doctor.mcj_number}/photo/", {"photo": jpeg()})
    client.post(f"/doctors/doctor/{doctor.mcj_number}/photo/", {"photo": jpeg(fmt="PNG")})
    assert StoredImage.objects.filter(kind="practitioner_photo").count() == 1


def test_non_image_upload_is_refused(client, agent, doctor):
    login(client, agent)
    bad = SimpleUploadedFile("evil.jpg", b"<?php echo 1; ?>" * 50, content_type="image/jpeg")
    resp = client.post(f"/doctors/doctor/{doctor.mcj_number}/photo/", {"photo": bad}, follow=True)
    assert "not a readable image" in resp.content.decode() and not StoredImage.objects.exists()


def test_check_register_button(client, agent, doctor):
    mcj(doctor.mcj_number, status="lapsed", valid=date(2025, 12, 31))
    login(client, agent)
    resp = client.post(f"/doctors/doctor/{doctor.mcj_number}/check-register/", follow=True)
    assert "Registration lapsed" in resp.content.decode()


def test_auditor_can_view_but_not_edit_doctor(client, auditor, doctor):
    login(client, auditor)
    assert client.get(f"/doctors/{doctor.mcj_number}/").status_code == 200
    assert client.post(f"/doctors/doctor/{doctor.mcj_number}/photo/", {"photo": jpeg()}).status_code == 403


# --- 3. Nurses ----------------------------------------------------------------------
def test_add_nurse_confirms_from_ncj_register(client, agent):
    ncj("47001")
    login(client, agent)
    resp = client.post(
        "/doctors/nurses/add/",
        {
            "ncj_number": "47001",
            "first_name": "",
            "last_name": "",
            "category": "rn",
            "practice_name": "KPH",
            "address_line1": "",
            "address_line2": "",
            "town": "",
            "parish": "KGN",
            "phone": "",
            "email": "",
        },
    )
    assert resp.status_code == 302
    nurse = Nurse.objects.get(ncj_number="47001")
    assert nurse.status == "confirmed" and nurse.last_name == "Ferguson" and nurse.verified_via == "register"


def test_lapsed_nurse_waits_for_manual_confirmation(client, agent, manager):
    ncj("47002", status="lapsed", valid=date(2025, 6, 30))
    nurse = doctor_services.add_nurse("47002", user=agent)
    assert nurse.status == "pending" and Notification.objects.filter(template="nurse-confirmation-needed").exists()
    login_verified(client, manager)
    assert "47002" in client.get("/doctors/confirmations/").content.decode()
    client.post("/doctors/nurses/47002/decide/", {"decision": "confirm", "note": "NCJ confirmed renewal by e-mail"})
    nurse.refresh_from_db()
    assert nurse.status == "confirmed" and nurse.verified_via == "manual"


def test_nurse_reject_needs_a_note(client, manager):
    Nurse.objects.create(ncj_number="47003", status="pending")
    login_verified(client, manager)
    client.post("/doctors/nurses/47003/decide/", {"decision": "reject", "note": ""})
    assert Nurse.objects.get(ncj_number="47003").status == "pending"


# --- 4. Staff: photo, ID, suspension ----------------------------------------------
def test_admin_records_id_number_encrypted_and_auditor_sees_it_masked(client, ict, agent, auditor):
    login_verified(client, ict)
    data = {
        "first_name": "Cc",
        "last_name": "Agent",
        "email": "a@x.invalid",
        "job_title": "Customer Care Officer",
        "phone": "",
        "staff_number": "S1001",
        "centre": agent.centre_id,
        "id_type": "nids",
        "id_number": "1234 5678 90",
        "id_expiry": "2030-01-01",
    }
    assert client.post(f"/accounts/staff/{agent.pk}/", data).status_code == 302
    agent.refresh_from_db()
    assert agent.id_number == "1234 5678 90" and agent.job_title == "Customer Care Officer"
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT id_number FROM accounts_user WHERE id=%s", [agent.pk])
        assert "1234" not in cur.fetchone()[0]
    client.logout()
    login(client, auditor)
    body = client.get(f"/accounts/staff/{agent.pk}/").content.decode()
    assert "1234 5678 90" not in body and "56789" not in body and "8 90" in body


def test_id_picture_visible_to_admin_and_audited_hidden_from_auditor(client, ict, agent, auditor):
    login_verified(client, ict)
    client.post(f"/accounts/staff/{agent.pk}/image/id/", {"image": jpeg(2400, 1500)})
    agent.refresh_from_db()
    doc = agent.id_document
    assert doc.kind == "staff_id" and doc.width == 1600
    resp = client.get(f"/images/{doc.pk}/")
    assert resp.status_code == 200 and resp["Cache-Control"] == "no-store"
    assert AuditEvent.objects.filter(action="staff.id_viewed").exists()
    client.logout()
    login(client, auditor)
    assert client.get(f"/images/{doc.pk}/").status_code == 404
    login_other = make_user("cc.other", "customer_care")
    client.logout()
    login(client, login_other)
    assert client.get(f"/images/{doc.pk}/").status_code == 404


def test_staff_set_their_own_photo_shown_in_top_bar(client, agent):
    login(client, agent)
    client.post("/accounts/me/photo/", {"image": jpeg()})
    agent.refresh_from_db()
    assert agent.photo and agent.photo.kind == "staff_photo"
    assert f"/images/{agent.photo_id}/" in client.get("/").content.decode()


def test_counter_staff_cannot_open_staff_directory(client, agent):
    login(client, agent)
    assert client.get("/accounts/staff/").status_code == 403


def test_suspension_ends_sessions_blocks_sign_in_and_reinstate_restores(client, ict, manager, agent):
    other = client.__class__()
    login(other, agent)
    assert other.get("/").status_code == 200
    login_verified(client, ict)
    resp = client.post(f"/accounts/staff/{agent.pk}/suspend/", {"reason": "HR investigation ref 114", "until": ""})
    assert resp.status_code == 302
    agent.refresh_from_db()
    assert agent.is_suspended and agent.suspended_by == ict
    assert AuditEvent.objects.filter(action="staff.suspended").exists()
    assert Notification.objects.filter(template="staff-suspended").exists()
    kicked = other.get("/")
    assert kicked.status_code == 302 and "/accounts/login/" in kicked["Location"]
    refused = client.__class__().post("/accounts/login/", {"username": agent.username, "password": PASSWORD})
    assert "suspended" in refused.content.decode()
    client.post(f"/accounts/staff/{agent.pk}/reinstate/", {"note": "cleared"})
    agent.refresh_from_db()
    assert not agent.is_suspended
    assert client.__class__().login(username=agent.username, password=PASSWORD)


def test_suspension_with_end_date_lifts_itself(agent, ict):
    agent.suspended_at = timezone.now() - timedelta(days=3)
    agent.suspended_until = timezone.now() - timedelta(minutes=1)
    agent.save()
    assert not agent.is_suspended


def test_cannot_suspend_yourself_or_the_last_administrator(client, ict, manager):
    login_verified(client, ict)
    client.post(f"/accounts/staff/{ict.pk}/suspend/", {"reason": "test"})
    ict.refresh_from_db()
    assert not ict.is_suspended
    client.logout()
    login_verified(client, manager)
    resp = client.post(f"/accounts/staff/{ict.pk}/suspend/", {"reason": "test"}, follow=True)
    ict.refresh_from_db()
    assert not ict.is_suspended and "only active application administrator" in resp.content.decode()


def test_suspension_needs_a_reason(client, ict, agent):
    login_verified(client, ict)
    client.post(f"/accounts/staff/{agent.pk}/suspend/", {"reason": ""})
    agent.refresh_from_db()
    assert not agent.is_suspended


def test_suspended_directory_user_is_refused(client, ict, settings):
    from apps.directory import ldap

    settings.LDAP = {**settings.LDAP, "ENABLED": True, "SERVER_URI": "mock://demo"}
    assert client.login(username="ad.campbell", password=ldap._demo_password())
    from django.contrib.auth import get_user_model

    u = get_user_model().objects.get(username="ad.campbell")
    u.suspended_at = timezone.now()
    u.save()
    client.logout()
    resp = client.post("/accounts/login/", {"username": "ad.campbell", "password": ldap._demo_password()})
    assert "suspended" in resp.content.decode()
    assert not UserSession.objects.filter(user=u, ended_at__isnull=True).exclude(created_at__lt=u.suspended_at).exists()
