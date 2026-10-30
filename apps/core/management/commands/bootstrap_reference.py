"""Reference data the platform needs to run (idempotent): centres, programmes, conditions, rejection reasons, parameters.

All of it is configurable afterwards in the back office; the lists are confirmed with NHF at inception.
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.core.models import Centre, Parameter
from apps.directory.models import GroupMapping
from apps.privacy.models import ProcessingActivity
from apps.rules.models import Benefit, MedicalCondition, Programme, RejectionReason, ScreeningTest

DRUG_SERV_HOURS = "Mon–Thu 8:30am–4:30pm · Fri 8:30am–3:30pm"
HEAD_OFFICE_HOURS = "Mon–Thu 7:00am–4:30pm · Fri 7:00am–3:30pm (call centre to 7:00pm Mon–Fri)"
# The 20 NHF Card print locations listed on the application form (revision 12, March 2026).
# code, name, parish, location as NHF describes it, kind
CENTRES = [
    ("HO", "Head Office", "AND", "The Towers, 25 Dominica Drive, New Kingston", "head_office"),
    ("MBJ", "Cornwall Regional Hospital Drug Serv", "JAM", "Cornwall Regional Hospital (CRH), St James", "drug_serv"),
    ("MDV", "Mandeville Regional Hospital Drug Serv", "MAN", "Mandeville Regional Hospital (MRH), Manchester", "drug_serv"),
    ("SPT", "Spanish Town Hospital Drug Serv", "CAT", "Spanish Town Hospital, St Catherine", "drug_serv"),
    ("LIN", "Linstead Hospital Drug Serv", "CAT", "Linstead Hospital, St Catherine", "drug_serv"),
    ("MBY", "Princess Margaret Hospital Drug Serv", "THO", "Princess Margaret Hospital, St Thomas", "drug_serv"),
    ("PMA", "Port Maria Hospital Drug Serv", "MAR", "Port Maria Hospital, St Mary", "drug_serv"),
    ("BRV", "Black River Hospital Drug Serv", "ELI", "Black River Hospital, St Elizabeth", "drug_serv"),
    ("LUC", "Noel Holmes Hospital Drug Serv", "HAN", "Noel Holmes Hospital, Hanover", "drug_serv"),
    ("PAN", "Port Antonio Hospital Drug Serv", "POR", "Port Antonio Hospital, Portland", "drug_serv"),
    ("HWT", "Union Square Drug Serv", "AND", "Union Square, Cross Roads", "drug_serv"),
    ("SAB", "St Ann's Bay Hospital Drug Serv", "ANN", "St Ann's Bay Hospital (SABH), St Ann", "drug_serv"),
    ("MPN", "May Pen Regional Hospital Drug Serv", "CLA", "May Pen Regional Hospital, Clarendon", "drug_serv"),
    ("PTM", "Greater Portmore Health Centre Drug Serv", "CAT", "Greater Portmore Health Centre, St Catherine", "drug_serv"),
    ("DTK", "Kingston Public Hospital Drug Serv", "KGN", "Kingston Public Hospital (KPH), Kingston", "drug_serv"),
    ("CHP", "Percy Junor Hospital Drug Serv", "MAN", "Percy Junor Hospital, Manchester", "drug_serv"),
    ("SCZ", "Santa Cruz Health Centre Drug Serv", "ELI", "Santa Cruz Health Centre, St Elizabeth", "drug_serv"),
    ("SAV", "Savanna-la-Mar Hospital Drug Serv", "WES", "Savanna-la-Mar Hospital, Westmoreland", "drug_serv"),
    ("LTN", "Lionel Town Hospital Drug Serv", "CLA", "Lionel Town Hospital, Clarendon", "drug_serv"),
    ("FAL", "Falmouth Hospital Drug Serv", "TRE", "Falmouth Hospital, Trelawny", "drug_serv"),
]
# Street address and telephone as NHF publishes them (nhf.org.jm/nhf-card, October 2026). Blank phone: not published.
CENTRE_DETAILS = {
    "HO": ("The Towers, 6th Floor, 25 Dominica Drive, Kingston 5", "876-906-1106 · 876-906-2293 · 876-906-9667"),
    "HWT": ("2 Union Square, Cross Roads, Kingston 5", "876-908-5479"),
    "DTK": ("Kingston Public Hospital, North Street, Kingston", "876-908-5473"),
    "SPT": ("Spanish Town Hospital, Burke Road, Spanish Town", ""),
    "LIN": ("Linstead Hospital, Rodney Hall Road, Linstead", "876-985-2359"),
    "PTM": ("5 West Greater Portmore, St Catherine", "876-908-5474"),
    "MPN": ("May Pen Hospital, Manchester Avenue, May Pen", "876-908-5471"),
    "LTN": ("Lionel Town Hospital, Bustamante Drive, Lionel Town", "876-986-3226"),
    "MDV": ("Mandeville Regional Hospital, 32 Hargreaves Avenue, Mandeville", "876-962-6479"),
    "CHP": ("Percy Junor Hospital, Spaldings, Christiana", "876-908-5470"),
    "SCZ": ("47 Coke Drive, Santa Cruz", "876-908-5467"),
    "BRV": ("Black River Hospital, 45 High Street, Black River", "876-634-3339"),
    "SAV": ("Savanna-la-Mar Public General Hospital, Barracks Road, Savanna-la-Mar", "876-955-9946"),
    "LUC": ("Noel Holmes Hospital, Fourth Charles Drive, Lucea", "876-956-2733"),
    "MBJ": ("Cornwall Regional Hospital & Mount Salem Health Centre, Mount Salem, Montego Bay", ""),
    "FAL": ("Falmouth Hospital, Rodney Street, Falmouth", "876-954-3250"),
    "SAB": ("St Ann's Bay Hospital, Seville, St Ann's Bay", "876-972-2272 · 876-972-2273"),
    "PMA": ("Port Maria Hospital, Trinity, Port Maria", "876-994-2228"),
    "PAN": ("Port Antonio Hospital, Naylors Hill, Port Antonio", "876-993-2646 · 876-613-8400"),
    "MBY": ("Princess Margaret Hospital, 54 Lyssons Road, Morant Bay", "876-908-5468"),
}

# Names used before v0.2.8 (invented placeholders); rows still carrying them are renamed to NHF's real locations.
OLD_CENTRE_NAMES = {
    "HO": "Head Office — Dominica Drive",
    "HWT": "Half-Way-Tree",
    "DTK": "Downtown Kingston",
    "PTM": "Portmore",
    "SPT": "Spanish Town",
    "LIN": "Linstead",
    "MPN": "May Pen",
    "MDV": "Mandeville",
    "SCZ": "Santa Cruz",
    "BRV": "Black River",
    "SAV": "Savanna-la-Mar",
    "LUC": "Lucea",
    "MBJ": "Montego Bay",
    "FAL": "Falmouth",
    "SAB": "St Ann's Bay",
    "PMA": "Port Maria",
    "PAN": "Port Antonio",
    "MBY": "Morant Bay",
    "CHP": "Christiana",
}
RETIRED_CENTRES = {"OHB": "Old Harbour", "OCR": "Ocho Rios"}  # not NHF print locations: deactivated, history kept

PROGRAMMES = [
    ("nhf", "NHF Individual Benefit", "Subsidy on prescribed drugs for the covered chronic conditions.", None, None, False, True, 1),
    ("jadep", "JADEP", "Jamaica Drugs for the Elderly Programme — assigned automatically at 60.", 60, None, True, True, 2),
    ("goj", "GOJ Programme", "Government-funded programme; covered conditions configured by the Fund.", None, None, False, True, 3),
    (
        "screening",
        "Screening benefits",
        "Pap smear or PSA test for applicants without a chronic illness; no doctor certification needed.",
        None,
        None,
        False,
        False,
        4,
    ),
]

# code, name, group, sex, min_age, max_age, programmes
# The 28 conditions on the Beneficiary Application Form, Section C (revision 12). Age bounds are clinical-consistency
# checks NHF can change in the back office; sex restrictions follow the condition.
CONDITIONS = [
    ("arthritis", "Arthritis", "Musculoskeletal", "", None, None, ["nhf", "jadep"]),
    ("asthma", "Asthma", "Respiratory", "", None, None, ["nhf", "jadep"]),
    ("adhd", "Attention Deficit Hyperactivity Disorder", "Mental health", "", None, None, ["nhf"]),
    ("bph", "Benign Prostatic Hyperplasia", "Genito-urinary", "M", 30, None, ["nhf", "jadep"]),
    ("bladder-cancer", "Bladder Cancer", "Cancer", "", None, None, ["nhf"]),
    ("breast-cancer", "Breast Cancer", "Cancer", "", 15, None, ["nhf"]),
    ("cervical-cancer", "Cervical Cancer", "Cancer", "F", None, None, ["nhf"]),
    ("copd", "Chronic Obstructive Pulmonary Disease", "Respiratory", "", 30, None, ["nhf"]),
    ("colorectal-cancer", "Colorectal Cancer", "Cancer", "", None, None, ["nhf"]),
    ("diabetes", "Diabetes", "Endocrine", "", None, None, ["nhf", "jadep"]),
    ("epilepsy", "Epilepsy", "Neurological", "", None, None, ["nhf"]),
    ("glaucoma", "Glaucoma", "Eye", "", None, None, ["nhf", "jadep"]),
    ("heart-failure", "Heart Failure", "Cardiovascular", "", None, None, ["nhf"]),
    ("high-cholesterol", "High Cholesterol", "Cardiovascular", "", None, None, ["nhf", "jadep"]),
    ("hypertension", "Hypertension", "Cardiovascular", "", None, None, ["nhf", "jadep"]),
    ("ibd", "Inflammatory Bowel Disease", "Digestive", "", None, None, ["nhf"]),
    ("ihd", "Ischaemic Heart Disease", "Cardiovascular", "", 18, None, ["nhf", "jadep"]),
    ("lung-cancer", "Lung Cancer", "Cancer", "", None, None, ["nhf"]),
    ("lupus", "Lupus", "Musculoskeletal", "", None, None, ["nhf"]),
    ("major-depression", "Major Depression", "Mental health", "", 10, None, ["nhf"]),
    ("multiple-myeloma", "Multiple Myeloma", "Cancer", "", None, None, ["nhf"]),
    ("parkinsons", "Parkinson's Disease", "Neurological", "", None, None, ["nhf"]),
    ("prostate-cancer", "Prostate Cancer", "Cancer", "M", 30, None, ["nhf"]),
    ("psychosis", "Psychosis", "Mental health", "", 10, None, ["nhf"]),
    ("rheumatic-heart", "RH Fever / RH Heart Disease", "Cardiovascular", "", None, None, ["nhf"]),
    ("sickle-cell", "Sickle Cell Disease", "Blood", "", None, None, ["nhf"]),
    ("thyroid", "Thyroid Disease", "Endocrine", "", None, None, ["nhf"]),
    ("vascular-disease", "Vascular Disease", "Cardiovascular", "", 18, None, ["nhf"]),
]
OLD_CONDITION_NAMES = {"rheumatic-heart": "Rheumatic Heart Disease"}

# Diagnostic / screening tests on the NHF Card (back of the application form).
# code, name, sex, min_age, max_age, requires_condition, frequency, frequency_with_condition, allowance_condition, without_doctor
SCREENINGS = [
    ("breast-receptor", "Breast Cancer Receptor Studies", "", None, None, "breast-cancer", "For NHFCard holders diagnosed with breast cancer", "", None, False),
    ("hba1c", "Haemoglobin A1c (HbA1c)", "", None, None, None, "One test per year", "Four tests per year, 90 days apart", "diabetes", False),
    ("psa", "Prostate-Specific Antigen (PSA) Test", "M", 40, 75, None, "One test per year", "Four tests per year, 90 days apart", "prostate-cancer", True),
    ("pap", "Pap Smear", "F", 21, 64, None, "One test every three years", "", None, True),
    ("ecg", "Electrocardiogram (ECG)", "", None, None, None, "One test per year", "", None, False),
    ("mammogram", "Mammogram", "F", 40, 74, None, "One test per year (high-risk women 30–40 with a doctor's referral)", "", None, False),
    ("echo", "Echocardiogram", "", None, None, None, "One test per year", "", None, False),
]

# NHF subsidy per test (J$). Increases effective 24 September 2026; echocardiogram added March 2026.
SCREENING_SUBSIDIES = {
    "pap": ("2450.00", date(2026, 9, 24)),
    "mammogram": ("3800.00", date(2026, 9, 24)),
    "ecg": ("1800.00", date(2026, 9, 24)),
    "hba1c": ("1500.00", date(2026, 9, 24)),
    "psa": ("1920.00", date(2026, 3, 18)),
    "echo": ("7500.00", date(2026, 3, 18)),
}

REASONS = [
    ("trn_mismatch", "Identity does not match the Tax Office record", True),
    ("trn_invalid", "TRN could not be validated", True),
    ("doctor_unconfirmed", "Doctor not confirmed by the Medical Council", True),
    ("incomplete_form", "Form incomplete or illegible", False),
    ("not_certified", "Condition not certified by a doctor", False),
    ("duplicate_application", "Duplicate application", False),
    ("not_eligible", "Not eligible for the programme", False),
    ("guardian_missing", "Guardian details missing for a minor", False),
    ("other", "Other (see note)", False),
]


PROCESSING = [
    (
        "Member registration and eligibility",
        "Register applicants for NHF benefits, decide eligibility and keep the member record.",
        "Necessary to perform the Fund's statutory functions; explicit consent for health data",
        "Applicants, members, guardians of minors",
        "Name, date of birth, gender, TRN/SRN, NIS number, contact details, address, guardian details, certified medical conditions",
        True,
        "Customer Care and back-office staff of the Fund",
        "For the life of the membership, then per the Fund's retention schedule",
    ),
    (
        "TRN validation",
        "Confirm the applicant's identity against the Tax Administration Jamaica register.",
        "Statutory function; identity verification required by the Fund",
        "Applicants, guardians",
        "TRN, name, date of birth, gender, address returned by the Tax Office",
        False,
        "Tax Administration Jamaica via the ICT Authority",
        "Validation results kept as audit evidence for the life of the record",
    ),
    (
        "Doctor validation",
        "Confirm the certifying doctor with the Medical Council of Jamaica.",
        "Statutory function",
        "Doctors",
        "Name, MCJ registration number, practice and contact details",
        False,
        "Medical Council of Jamaica",
        "While the doctor remains on the NHF Doctors register",
    ),
    (
        "Claims adjudication and card production",
        "Pass beneficiary records to the claims adjudicator and produce the NHF Card.",
        "Necessary to deliver the benefit",
        "Members",
        "Member number, name, date of birth, programmes, card data",
        True,
        "Claims adjudication system (PHI); card production (ID Works)",
        "For the life of the membership",
    ),
    (
        "Notifications",
        "Tell applicants about their application by SMS and e-mail.",
        "Necessary to deliver the service",
        "Applicants, members",
        "Mobile number, e-mail address, tracking number",
        False,
        "SMS gateway provider; e-mail relay",
        "Message log kept 12 months",
    ),
    (
        "Staff accounts and audit",
        "Control access to the system and keep an audit trail of every action.",
        "Legitimate interest and security obligations under the Act",
        "Staff users",
        "Name, username, centre, roles, sign-in records, pages and records accessed, IP address",
        False,
        "Fund ICT and auditors",
        "Access log 12 months; audit trail for the life of the system",
    ),
]


PROCESSING_V022 = [
    (
        "Nurse validation",
        "Confirm nurses and midwives with the Nursing Council of Jamaica and keep the Fund's nurses register.",
        "Statutory function",
        "Nurses and midwives",
        "Name, NCJ registration number, category, workplace and address, contact details, photo, register status",
        False,
        "Nursing Council of Jamaica",
        "While the nurse remains on the nurses register",
    ),
    (
        "Staff identity records",
        "Identify staff who handle member data: photo, government ID and ID number held for vetting and access control.",
        "Employment obligations; security obligations under the Act",
        "Staff users",
        "Photo, ID type, ID number (encrypted), ID expiry, ID picture (encrypted); suspension records",
        False,
        "Fund ICT and Human Resources",
        "While employed; erased automatically a set period after the account is disabled (parameter staff-id-retention-days)",
    ),
    (
        "Directory sign-in",
        "Sign staff in with their NHF network account and keep roles in step with Active Directory / Entra ID groups.",
        "Legitimate interest and security obligations under the Act",
        "Staff users",
        "Username, name, e-mail, directory object id, group memberships",
        False,
        "None outside the Fund (read-only queries to the Fund's own directory)",
        "While the account exists",
    ),
]
OLD_SECURITY_MEASURES = "Role-based access, MFA for privileged roles, field-level encryption of sensitive data, append-only audit, TLS"
SECURITY_MEASURES = (
    "Role-based access with need-to-know masking; two-step sign-in for all staff; field-level encryption of sensitive data and images; "
    "append-only audit and access log; TLS; security alerts; retention sweep"
)
OLD_DOCTOR_CATEGORIES = "Name, MCJ registration number, practice and contact details"
# Parameter values that are still at a previous release's default are moved to the new default; edited values are left alone.
OLD_PARAMETER_DEFAULTS = {
    "nis-format-regex": [r"^([A-Z][0-9]{6}|[0-9]{9})$"],
    "privacy-notice-version": ["2026-10"],
    "privacy-notice-text": [
        "The National Health Fund collects your personal details and the medical conditions certified by your doctor to register you for "
        "NHF benefits, produce your NHF Card and process your benefit claims. Your information is shared only with the Tax Administration "
        "(TRN validation), the Medical Council (doctor confirmation), the claims adjudicator and card production, and is kept in line with "
        "the Fund's retention policy. You may ask for a copy of your information or for it to be corrected."
    ],
}

# Suggested AD group names; NHF renames or remaps them in the back office.
GROUP_MAPPINGS = [
    ("NHF-MRS-CustomerCare", "customer_care", None),
    ("NHF-MRS-Supervisors", "supervisor", None),
    ("NHF-MRS-Managers", "manager", None),
    ("NHF-MRS-BackOffice", "back_office", None),
    ("NHF-MRS-AppAdmins", "ict_admin", None),
    ("NHF-MRS-Auditors", "auditor", None),
    ("NHF-MRS-DPO", "dpo", None),
    ("NHF-MRS-PrintOperators", "print_operator", None),
    ("NHF-Centre-HWT", "", "HWT"),
    ("NHF-Centre-MBJ", "", "MBJ"),
    ("NHF-Centre-HO", "", "HO"),
]


class Command(BaseCommand):
    help = "Load reference data (idempotent; existing rows are left as configured)."

    def handle(self, *args, **opts):
        for code, name, parish, address, kind in CENTRES:
            hours = HEAD_OFFICE_HOURS if kind == "head_office" else DRUG_SERV_HOURS
            centre, created = Centre.objects.get_or_create(
                code=code, defaults={"name": name, "parish": parish, "address": address, "kind": kind, "hours": hours}
            )
            if not created and (centre.name == OLD_CENTRE_NAMES.get(code) or not centre.address):
                Centre.objects.filter(pk=centre.pk).update(
                    name=name if centre.name == OLD_CENTRE_NAMES.get(code) else centre.name,
                    parish=parish,
                    address=address,
                    kind=kind,
                    hours=centre.hours or hours,
                )
        defaults_by_code = {c[0]: c[3] for c in CENTRES}
        for code, (street, phone) in CENTRE_DETAILS.items():
            centre = Centre.objects.filter(code=code).first()
            if centre is None:
                continue
            updates = {}
            if centre.address in ("", defaults_by_code.get(code)):  # never overwrite an address the back office has edited
                updates["address"] = street
            if not centre.phone and phone:
                updates["phone"] = phone
            if updates:
                Centre.objects.filter(pk=centre.pk).update(**updates)
        for code, old_name in RETIRED_CENTRES.items():
            Centre.objects.filter(code=code, name=old_name).update(is_active=False, prints_cards=False)
        progs = {}
        for code, name, desc, lo, hi, auto, req, order in PROGRAMMES:
            progs[code], _ = Programme.objects.get_or_create(
                code=code,
                defaults={"name": name, "description": desc, "min_age": lo, "max_age": hi, "auto_assign": auto, "requires_condition": req, "sort_order": order},
            )
        Benefit.objects.get_or_create(programme=progs["nhf"], code="drug-subsidy", defaults={"name": "Prescription drug subsidy"})
        Benefit.objects.get_or_create(programme=progs["jadep"], code="drug-copay", defaults={"name": "Fixed co-payment per prescription item"})
        for code, name, group, sex, lo, hi, programmes in CONDITIONS:
            cond, created = MedicalCondition.objects.get_or_create(
                code=code, defaults={"name": name, "group": group, "sex_restriction": sex, "min_age": lo, "max_age": hi}
            )
            if created:
                cond.programmes.set([progs[p] for p in programmes])
            elif cond.name == OLD_CONDITION_NAMES.get(code):
                MedicalCondition.objects.filter(pk=cond.pk).update(name=name)
        for order, (code, name, sex, lo, hi, req, freq, freq_cond, allow_cond, no_doc) in enumerate(SCREENINGS):
            ScreeningTest.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "sex_restriction": sex,
                    "min_age": lo,
                    "max_age": hi,
                    "requires_condition": MedicalCondition.objects.filter(code=req).first() if req else None,
                    "frequency": freq,
                    "frequency_with_condition": freq_cond,
                    "allowance_condition": MedicalCondition.objects.filter(code=allow_cond).first() if allow_cond else None,
                    "without_doctor": no_doc,
                    "sort_order": order,
                },
            )
            test = ScreeningTest.objects.get(code=code)
            if code in SCREENING_SUBSIDIES and test.subsidy is None:
                test.subsidy, test.subsidy_from = Decimal(SCREENING_SUBSIDIES[code][0]), SCREENING_SUBSIDIES[code][1]
                test.save(update_fields=["subsidy", "subsidy_from"])
            if code == "psa" and test.allowance_condition is None:  # four a year for prostate-cancer members (March 2026)
                test.frequency_with_condition, test.allowance_condition = freq_cond, MedicalCondition.objects.filter(code=allow_cond).first()
                test.save(update_fields=["frequency_with_condition", "allowance_condition"])
        for code, label, system in REASONS:
            RejectionReason.objects.get_or_create(code=code, defaults={"label": label, "is_system": system})
        for key, (value, desc) in Parameter.DEFAULTS.items():
            param, created = Parameter.objects.get_or_create(key=key, defaults={"value": value, "description": desc})
            if not created and param.value in OLD_PARAMETER_DEFAULTS.get(key, []):
                param.value, param.description = value, desc
                param.save()
        for name, purpose, basis, subjects, cats, sensitive, recipients, retention in PROCESSING + PROCESSING_V022:
            ProcessingActivity.objects.get_or_create(
                name=name,
                defaults={
                    "purpose": purpose,
                    "lawful_basis": basis,
                    "data_subjects": subjects,
                    "data_categories": cats,
                    "sensitive": sensitive,
                    "recipients": recipients,
                    "retention": retention,
                    "security_measures": SECURITY_MEASURES,
                },
            )
        ProcessingActivity.objects.filter(security_measures=OLD_SECURITY_MEASURES).update(security_measures=SECURITY_MEASURES)
        ProcessingActivity.objects.filter(name="Doctor validation", data_categories=OLD_DOCTOR_CATEGORIES).update(
            data_categories="Name, MCJ registration number, specialty, practice name and address, contact details, photo, register status"
        )
        if not GroupMapping.objects.exists():
            for group, role, centre in GROUP_MAPPINGS:
                GroupMapping.objects.create(source="ad", group=group, role=role, centre=Centre.objects.filter(code=centre).first() if centre else None)
        Parameter.objects.get_or_create(
            key="mock-trn-service-down", defaults={"value": False, "description": "Demo only: makes the mock TRN adapter time out, to show the outage path."}
        )
        self.stdout.write(
            f"reference: {Centre.objects.count()} centres, {Programme.objects.count()} programmes, {MedicalCondition.objects.count()} conditions, {RejectionReason.objects.count()} reasons"
        )
