"""v0.2.8: the paper form (Beneficiary Application Form rev. 12) digitised; How to apply page; pick-up slip; subsidies."""

import base64
import io
from datetime import date

import pytest
from django.utils import timezone
from PIL import Image

from apps.core.models import AuditEvent, Centre, StoredImage
from apps.members import services
from apps.members.models import Application
from apps.rules.models import MedicalCondition, ScreeningTest

from .conftest import PASSWORD
from .test_counter_journey import complete, start

pytestmark = pytest.mark.django_db


def rules(app):
    return {(f.rule, f.level) for f in services.evaluate(app).findings}


def messages_for(app, rule):
    return [f.message for f in services.evaluate(app).findings if f.rule == rule]


def login(client, user):
    assert client.login(username=user.username, password=PASSWORD)


def signature_png():
    buf = io.BytesIO()
    Image.new("RGB", (300, 100), "white").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# --- What the back of the form requires ------------------------------------------------
def test_new_form_needs_signatures_address_and_contact(agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.doctor_mcj = doctor.mcj_number
    services.resolve_doctor(app, user=agent)
    app.consent_given = True
    app.address_line1 = app.parish = ""  # the TRN service pre-fills the address; this form left it blank
    app.save()
    services.set_conditions(app, [(MedicalCondition.objects.get(code="hypertension"), "mild")])
    form_errors = " ".join(f.message for f in services.evaluate(app).errors if f.rule == "FORM")
    assert "signed the declaration" in form_errors and "doctor's signature" in form_errors and "address" in form_errors and "contact" in form_errors
    app = complete(app, agent, doctor, "hypertension")
    assert app.status == "ready"


def test_replacement_card_needs_only_name_trn_and_signature(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    with run_commits():
        change = services.start_application(user=agent, centre=agent.centre, channel="walk_in", received_at=timezone.now(), kind="change", member=member)
    change.refresh_from_db()
    change.reprint_reason = "replacement"
    change.address_line1 = change.phone_mobile = change.phone_home = change.email = ""
    change.save()
    assert ("FORM", "error") in rules(change)  # not signed yet
    change.declaration_signed = True
    change.save()
    assert ("FORM", "error") not in rules(change)


def test_mailed_form_needs_trn_photocopy(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14), channel="mail"), agent, doctor, "hypertension")
    assert any("photocopy" in m for m in messages_for(app, "FORM"))
    app.trn_copy_attached = True
    app.form_serial = "9794257"
    app.save()
    assert services.refresh_status(app).status == "ready"


def test_condition_total_mismatch_is_a_warning(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.conditions_total = 2
    app.save()
    assert ("FORM", "warning") in rules(app) and services.refresh_status(app).status == "ready"


# --- Screening-only and Section B triggers ----------------------------------------------
def test_screening_only_pap_needs_no_doctor_or_condition(agent, taj, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.screening_only = True
    app.consent_given = app.declaration_signed = True
    app.address_line1, app.parish, app.phone_mobile = "12 Hope Road", "AND", "876-555-0100"
    app.save()
    outcome = services.evaluate(app)
    assert outcome.ok, [f.message for f in outcome.errors]
    assert any(f.rule == "SCREENING" and "Pap Smear" in f.message for f in outcome.findings)
    assert "screening" in [p.code for p in outcome.programmes]
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    assert member.enrolments.filter(programme__code="screening").exists()


def test_screening_only_refused_when_age_and_sex_do_not_fit(agent, taj, run_commits):
    # A man of 30 qualifies for neither Pap smear nor PSA (men 40–75).
    from apps.identity.models import TajIdentity

    TajIdentity.objects.create(trn="100200399", first_name="Andre", last_name="Lewis", dob=date(1996, 5, 5), gender="M")
    app = start(agent, run_commits, "100200399", "Andre", "Lewis", date(1996, 5, 5))
    app.screening_only = True
    app.save()
    assert ("SCREENING", "error") in rules(app)


def test_incapacitated_adult_needs_section_b(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.incapacitated = True
    app.save()
    assert any("incapacitated" in m for m in messages_for(app, "BR10004"))
    app.guardian_type, app.guardian_name = "guardian", "Janet Brown"
    app.save()
    assert ("BR10004", "error") not in rules(app)


# --- Subsidies ------------------------------------------------------------------------------
def test_disability_double_subsidy_needs_jcpd_proof_and_reaches_the_member(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.plwd = True
    app.save()
    assert ("PLWD", "error") in rules(app)
    app.jcpd_evidence, app.jcpd_number = "id_card", "JC-104455"
    app.save()
    assert ("PLWD", "info") in rules(app)
    services.refresh_status(app)
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    assert member.plwd and member.jcpd_number == "JC-104455"


def test_child_double_subsidy_is_noted(agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200302", "Tyrese", "Brown", date(2014, 7, 2)), agent, doctor, "asthma", guardian=True)
    assert any("under 19" in m for m in messages_for(app, "CHILD"))


def test_screening_subsidies_and_centre_details_seeded():
    assert ScreeningTest.objects.get(code="pap").subsidy == 2450
    assert ScreeningTest.objects.get(code="echo").subsidy == 7500
    psa = ScreeningTest.objects.get(code="psa")
    assert psa.allowance_condition.code == "prostate-cancer" and psa.eligible(age=60, gender="M", condition_codes={"prostate-cancer"})[1].startswith("Four")
    scz = Centre.objects.get(code="SCZ")
    assert scz.address == "47 Coke Drive, Santa Cruz" and scz.phone == "876-908-5467"


# --- Counter screen -----------------------------------------------------------------------
def _post(client, app, doctor, agent, **extra):
    data = {
        "consent_given": "on",
        "declaration_signed": "on",
        "doctor_signed": "on",
        "address_line1": "12 Hope Road",
        "parish": "AND",
        "phone_mobile": "876-555-0100",
        "doctor_mcj": doctor.mcj_number,
        "collection_centre": agent.centre_id,
        "form_revision": "12",
        f"cond_{MedicalCondition.objects.get(code='hypertension').pk}": "on",
        f"sev_{MedicalCondition.objects.get(code='hypertension').pk}": "severe",
    }
    data.update(extra)
    return client.post(f"/members/applications/{app.tracking_number}/", data)


def test_counter_screen_saves_every_section(client, agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    login(client, agent)
    page = client.get(f"/members/applications/{app.tracking_number}/").content.decode()
    for text in ("Applicant information", "Parent / guardian / field officer / institution", "To be completed by the doctor", "Form serial no.", "sigpad"):
        assert text in page, text
    response = _post(
        client,
        app,
        doctor,
        agent,
        form_serial="9794257",
        title="Mrs",
        occupation="Teacher",
        post_office="Constant Spring",
        doctor_office_address="5 Hope Road",
        doctor_parish="AND",
        doctor_office_phone="876-927-0000",
        certified_on=timezone.localdate().isoformat(),
        conditions_total="1",
        guardian_id_number="",
    )
    assert response.status_code == 302
    app.refresh_from_db()
    assert (app.form_serial, app.title, app.occupation, app.post_office, app.conditions_total) == ("9794257", "Mrs", "Teacher", "Constant Spring", 1)
    assert app.conditions.get().severity == "severe" and app.status == "ready"


def test_form_serial_must_be_digits_and_unique(client, agent, taj, doctor, run_commits):
    first = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    Application.objects.filter(pk=first.pk).update(form_serial="9794257")
    second = start(agent, run_commits, "100200303", "Winston", "Grant", date(1958, 11, 20))
    login(client, agent)
    page = _post(client, second, doctor, agent, form_serial="97A4257").content.decode()
    assert "digits printed on the form" in page
    page = _post(client, second, doctor, agent, form_serial="9794257").content.decode()
    assert f"already recorded on application {first.tracking_number}" in page and "Not saved — check form serial no." in page


def test_signature_pad_stores_an_encrypted_signature(client, agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    login(client, agent)
    _post(client, app, doctor, agent, declaration_signed="", signature_data=signature_png())
    app.refresh_from_db()
    assert app.signature and app.signature.kind == "signature" and app.declaration_signed and app.declaration_date == timezone.localdate()
    assert AuditEvent.objects.filter(action="application.signature_captured").exists()
    assert client.get(f"/images/{app.signature_id}/").status_code == 200


def test_bad_signature_data_is_refused(client, agent, taj, doctor, run_commits):
    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    login(client, agent)
    _post(client, app, doctor, agent, declaration_signed="", signature_data="data:image/png;base64,!!!notbase64")
    app.refresh_from_db()
    assert app.signature is None and not app.declaration_signed and not StoredImage.objects.filter(kind="signature").exists()


def test_pickup_slip(client, agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    app.form_serial = "9794257"
    app.save()
    login(client, agent)
    page = client.get(f"/members/applications/{app.tracking_number}/slip/").content.decode()
    assert app.tracking_number in page and "9794257" in page and "•••-•••-301" in page and "100200301" not in page
    assert agent.centre.name in page and AuditEvent.objects.filter(action="application.slip_printed").exists()


def test_member_profile_shows_screening_tests(client, agent, taj, doctor, run_commits):
    app = complete(start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14)), agent, doctor, "hypertension")
    with run_commits():
        member = services.approve(app.pk, user=agent).member
    login(client, agent)
    page = client.get(f"/members/{member.member_number}/").content.decode()
    assert "Screening tests and subsidy" in page and "Pap Smear" in page and "Mammogram" in page and "Prostate" not in page


# --- Public How to apply page -------------------------------------------------------------------
def test_how_to_apply_is_public_and_driven_by_reference_data(client):
    response = client.get("/how-to-apply/")
    assert response.status_code == 200
    page = response.content.decode()
    for text in ("In person", "By mail", "Online, through your doctor", "P.O. Box 412, Kingston 10", "3 to 4 weeks", "What NHF staff see", "Who can change it"):
        assert text in page, text
    assert f"Illnesses covered ({MedicalCondition.objects.filter(is_active=True).count()})" in page
    assert "Santa Cruz Health Centre Drug Serv" in page and "J$2,450" in page
    assert "js/howto.js" in page and "/how-to-apply/" in client.get("/accounts/login/").content.decode()


def test_how_to_apply_open_to_signed_in_staff_before_two_step(client, manager):
    login(client, manager)  # manager must set up two-step before reaching staff pages
    assert client.get("/how-to-apply/").status_code == 200


def test_date_pickers_render_iso_dates_so_a_resave_keeps_them(agent, taj, run_commits):
    """<input type="date"> only accepts YYYY-MM-DD; a locale format shows blank and is wiped on the next save."""
    from apps.accounts.staff import StaffForm
    from apps.members.forms import ApplicationForm, IdDocumentForm
    from apps.members.models import Member

    app = start(agent, run_commits, "100200301", "Marcia", "Campbell", date(1979, 3, 14))
    app.declaration_date = app.certified_on = date(2026, 10, 1)
    form = ApplicationForm(instance=app)
    assert (str(form["declaration_date"]) + str(form["certified_on"])).count('value="2026-10-01"') == 2
    agent.id_issue_date = date(2020, 1, 2)
    assert 'value="2020-01-02"' in str(StaffForm(instance=agent)["id_issue_date"])
    assert 'value="2031-05-06"' in str(IdDocumentForm(instance=Member(id_expiry=date(2031, 5, 6)))["id_expiry"])
