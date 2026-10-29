"""Reference data the platform needs to run (idempotent): centres, programmes, conditions, rejection reasons, parameters.

All of it is configurable afterwards in the back office; the lists are confirmed with NHF at inception.
"""

from django.core.management.base import BaseCommand

from apps.core.models import Centre, Parameter
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
            Parameter.objects.get_or_create(key=key, defaults={"value": value, "description": desc})
        Parameter.objects.get_or_create(
            key="mock-trn-service-down", defaults={"value": False, "description": "Demo only: makes the mock TRN adapter time out, to show the outage path."}
        )
        self.stdout.write(
            f"reference: {Centre.objects.count()} centres, {Programme.objects.count()} programmes, {MedicalCondition.objects.count()} conditions, {RejectionReason.objects.count()} reasons"
        )
