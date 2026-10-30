"""Reference data the platform needs to run (idempotent): centres, programmes, conditions, rejection reasons, parameters.

All of it is configurable afterwards in the back office; the lists are confirmed with NHF at inception.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Centre, Parameter
from apps.directory.models import GroupMapping
from apps.privacy.models import ProcessingActivity
from apps.rules.models import Benefit, MedicalCondition, Programme, RejectionReason

CENTRES = [
    ("HO", "Head Office — Dominica Drive", "AND"),
    ("HWT", "Half-Way-Tree", "AND"),
    ("DTK", "Downtown Kingston", "KGN"),
    ("PTM", "Portmore", "CAT"),
    ("SPT", "Spanish Town", "CAT"),
    ("LIN", "Linstead", "CAT"),
    ("OHB", "Old Harbour", "CAT"),
    ("MPN", "May Pen", "CLA"),
    ("MDV", "Mandeville", "MAN"),
    ("SCZ", "Santa Cruz", "ELI"),
    ("BRV", "Black River", "ELI"),
    ("SAV", "Savanna-la-Mar", "WES"),
    ("LUC", "Lucea", "HAN"),
    ("MBJ", "Montego Bay", "JAM"),
    ("FAL", "Falmouth", "TRE"),
    ("SAB", "St Ann's Bay", "ANN"),
    ("OCR", "Ocho Rios", "ANN"),
    ("PMA", "Port Maria", "MAR"),
    ("PAN", "Port Antonio", "POR"),
    ("MBY", "Morant Bay", "THO"),
    ("CHP", "Christiana", "MAN"),
]

PROGRAMMES = [
    ("nhf", "NHF Individual Benefit", "Subsidy on prescribed drugs for the covered chronic conditions.", None, None, False, True, 1),
    ("jadep", "JADEP", "Jamaica Drugs for the Elderly Programme — assigned automatically at 60.", 60, None, True, True, 2),
    ("goj", "GOJ Programme", "Government-funded programme; covered conditions configured by the Fund.", None, None, False, True, 3),
]

# code, name, group, sex, min_age, max_age, programmes
CONDITIONS = [
    ("arthritis", "Arthritis", "Musculoskeletal", "", None, None, ["nhf", "jadep"]),
    ("asthma", "Asthma", "Respiratory", "", None, None, ["nhf", "jadep"]),
    ("bph", "Benign Prostatic Hyperplasia", "Genito-urinary", "M", 30, None, ["nhf", "jadep"]),
    ("breast-cancer", "Breast Cancer", "Cancer", "", 15, None, ["nhf"]),
    ("copd", "Chronic Obstructive Pulmonary Disease", "Respiratory", "", 30, None, ["nhf"]),
    ("diabetes", "Diabetes", "Endocrine", "", None, None, ["nhf", "jadep"]),
    ("epilepsy", "Epilepsy", "Neurological", "", None, None, ["nhf"]),
    ("glaucoma", "Glaucoma", "Eye", "", None, None, ["nhf", "jadep"]),
    ("high-cholesterol", "High Cholesterol", "Cardiovascular", "", None, None, ["nhf", "jadep"]),
    ("hypertension", "Hypertension", "Cardiovascular", "", None, None, ["nhf", "jadep"]),
    ("ihd", "Ischaemic Heart Disease", "Cardiovascular", "", 18, None, ["nhf", "jadep"]),
    ("major-depression", "Major Depression", "Mental health", "", 10, None, ["nhf"]),
    ("prostate-cancer", "Prostate Cancer", "Cancer", "M", 30, None, ["nhf"]),
    ("psychosis", "Psychosis", "Mental health", "", 10, None, ["nhf"]),
    ("rheumatic-heart", "Rheumatic Heart Disease", "Cardiovascular", "", None, None, ["nhf"]),
    ("vascular-disease", "Vascular Disease", "Cardiovascular", "", 18, None, ["nhf"]),
]

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
        for code, name, parish in CENTRES:
            Centre.objects.get_or_create(code=code, defaults={"name": name, "parish": parish})
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
