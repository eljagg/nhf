"""Synthetic demonstration data: 5,000 members across 21 centres, a synthetic TRN register, doctors, open queues and demo users.

Everything here is invented. Run with --force (refuses otherwise); --if-missing skips when demo data exists.
The named demo cases used in the demonstration script are listed in docs/demo-script.md.
"""

import os
import random
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.cards.models import Card, clean_card_name
from apps.core.models import Centre, StoredImage
from apps.doctors.models import CouncilRegisterEntry, Doctor, Nurse
from apps.identity.models import TajIdentity
from apps.interactions.models import Interaction
from apps.members.models import Application, Enrolment, Guardian, Member, MemberCondition
from apps.rules.models import MedicalCondition, Programme

FIRST_F = "Marcia Shanique Kerry-Ann Tamara Simone Natalie Keisha Sophia Andrea Petrina Nadine Tanesha Latoya Rochelle Camille Judith Beverley Paulette Yvonne Hyacinth Monique Kimone Stacy-Ann Annmarie Gail Claudette Sharon Dahlia Joan Veronica".split()
FIRST_M = "Andre Winston Delroy Kevin Omar Dwayne Ricardo Damion Garfield Leroy Carlton Everton Tyrese Jermaine Romario Kemar Shane Devon Clive Lloyd Desmond Errol Fitzroy Oneil Marlon Junior Trevor Rohan Courtney Patrick".split()
MIDDLE = "Ann Marie Elizabeth Grace Louise Anthony George Michael Patrick Alexander Joseph Delroy Beverley".split()
LAST = (
    "Brown Williams Campbell Smith Thompson Johnson Grant Clarke Reid Lewis Morgan Henry Walker Robinson Wright Gordon Bailey Stewart Edwards Francis "
    "Allen Mitchell Gayle Ellis Bennett Hall Palmer Davis Wilson Taylor McKenzie Forbes Spence Simpson Hamilton Miller Nelson Graham Barrett Chambers"
).split()
STREETS = "Hope Road|Constant Spring Road|Old Hope Road|Main Street|Barbican Road|Molynes Road|Washington Boulevard|Red Hills Road|Manchester Road|Market Street|Church Street|Spanish Town Road".split(
    "|"
)
DOCTOR_SPECIALTIES = [
    "General practice",
    "Internal medicine",
    "Family medicine",
    "Cardiology",
    "Endocrinology",
    "Psychiatry",
    "Ophthalmology",
    "Oncology",
    "Paediatrics",
]

# Synthetic staging data only; production never runs this command.
DEMO_PASSWORD_DEFAULT = "NhfDemo-2026!"  # noqa: S105  # nosec B105

# Named demo cases (docs/demo-script.md)
DEMO_TAJ = [
    ("100200301", "Marcia", "Angela", "Campbell", date(1979, 3, 14), "F", "12 Hope Road", "Kingston 6", "AND", "walk-in adult — clean match"),
    ("100200302", "Tyrese", "", "Brown", date(2014, 7, 2), "M", "4 Main Street", "May Pen", "CLA", "minor — guardian required"),
    ("100200303", "Winston", "Delroy", "Grant", date(1958, 11, 20), "M", "27 Manchester Road", "Mandeville", "MAN", "66 years — JADEP assigned automatically"),
    ("100200304", "Shanique", "Ann-Marie", "Williams", date(1990, 5, 9), "F", "8 Barbican Road", "Kingston 8", "AND", "form says 'Shaniqua' — mismatch"),
    ("100200305", "Paulette", "", "Reid", date(1972, 9, 1), "F", "15 Church Street", "Montego Bay", "JAM", "female — BPH is blocked"),
    (
        "100200306",
        "Kerry-Ann",
        "",
        "Thompson-Clarke",
        date(1985, 1, 23),
        "F",
        "3 Molynes Road",
        "Kingston 10",
        "AND",
        "member renamed at TAJ — change form reprint",
    ),
    ("100200307", "Andre", "Michael", "Lewis", date(1968, 6, 30), "M", "44 Red Hills Road", "Kingston 19", "AND", "existing member — contact edit"),
]
DEMO_MEMBERS = {  # members already registered, with what NHF held at registration
    "100200306": {"last_name": "Thompson"},
    "100200307": {"nis_number": "B204517"},
}


TOWNS = {
    "KGN": ["Downtown Kingston", "Allman Town", "Rae Town"],
    "AND": ["Half-Way-Tree", "Liguanea", "Constant Spring", "Papine", "Cross Roads"],
    "CAT": ["Spanish Town", "Portmore", "Old Harbour", "Linstead"],
    "CLA": ["May Pen", "Chapelton", "Lionel Town"],
    "MAN": ["Mandeville", "Christiana", "Porus"],
    "ELI": ["Black River", "Santa Cruz", "Junction"],
    "WES": ["Savanna-la-Mar", "Negril", "Whitehouse"],
    "HAN": ["Lucea", "Hopewell", "Green Island"],
    "JAM": ["Montego Bay", "Cambridge", "Anchovy"],
    "TRE": ["Falmouth", "Clark's Town", "Duncans"],
    "ANN": ["St Ann's Bay", "Ocho Rios", "Brown's Town"],
    "MAR": ["Port Maria", "Highgate", "Annotto Bay"],
    "POR": ["Port Antonio", "Buff Bay", "Hope Bay"],
    "THO": ["Morant Bay", "Yallahs", "Seaforth"],
}
HOSPITALS = {
    "KGN": "Kingston Public Hospital",
    "AND": "University Hospital of the West Indies",
    "CAT": "Spanish Town Hospital",
    "CLA": "May Pen Hospital",
    "MAN": "Mandeville Regional Hospital",
    "ELI": "Black River Hospital",
    "WES": "Savanna-la-Mar Public General Hospital",
    "HAN": "Noel Holmes Hospital",
    "JAM": "Cornwall Regional Hospital",
    "TRE": "Falmouth Public General Hospital",
    "ANN": "St Ann's Bay Regional Hospital",
    "MAR": "Port Maria Hospital",
    "POR": "Port Antonio Hospital",
    "THO": "Princess Margaret Hospital",
}
# Named council-register demo cases (docs/demo-script.md)
REGISTER_DEMO = [
    # council, number, title, first, last, specialty, status, valid_until
    ("mcj", "20015", "Dr", "Natalie", "Grant-Wright", "Paediatrics", "active", date(2027, 12, 31)),
    ("mcj", "20022", "Dr", "Ewan", "Blackwood", "General practice", "suspended", date(2027, 12, 31)),
    ("mcj", "20029", "Dr", "Hortense", "Lindo", "Internal medicine", "lapsed", date(2025, 12, 31)),
    ("ncj", "47001", "Nurse", "Kadian", "Ferguson", "Registered Nurse", "active", date(2027, 6, 30)),
    ("ncj", "47002", "Nurse", "Sherona", "Pusey", "Registered Midwife", "lapsed", date(2025, 6, 30)),
]
NURSE_CATEGORY_LABELS = dict(Nurse.CATEGORIES)


class Command(BaseCommand):
    help = "Seed synthetic demonstration data (requires --force)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--if-missing", action="store_true", help="Skip when demo data is already present.")
        parser.add_argument("--members", type=int, default=5000)

    def handle(self, *args, **opts):
        if not opts["force"]:
            raise CommandError("Refusing to seed without --force (synthetic data; never on production).")
        from django.conf import settings

        if not settings.DEMO_MODE:
            self.stdout.write(self.style.WARNING("DEMO_MODE is off: demo data (known passwords) is never seeded outside demo mode. Skipped."))
            return
        if opts["if_missing"] and TajIdentity.objects.exists():
            done = False
            ho = Centre.objects.filter(code="HO").first()
            if ho and get_user_model().objects.filter(username="sup.henry").exclude(centre=ho).update(centre=ho):  # v0.2.7: online unit at Head Office
                self.stdout.write("demo: sup.henry moved to the Head Office online unit")
                done = True
            if not CouncilRegisterEntry.objects.exists():  # upgrade from v0.2.1: add practitioners without a full reseed
                with transaction.atomic():
                    self._practitioners(random.Random(1473))  # noqa: S311  # nosec B311
                self.stdout.write(f"demo: practitioners added ({Nurse.objects.count()} nurses, {CouncilRegisterEntry.objects.count()} council register rows)")
                done = True
            if Member.objects.filter(Q(nis_number="") | Q(id_type="")).exists():  # upgrade to v0.2.6
                with transaction.atomic():
                    filled = self._identity_details(random.Random(1616))  # noqa: S311  # nosec B311
                self.stdout.write(f"demo: NIS numbers and ID documents filled for {filled} people")
                done = True
            if Application.objects.filter(status__in=("approved", "rejected")).count() < 200:  # upgrade to v0.3: a year of history for reports
                with transaction.atomic():
                    made = self._history(random.Random(2026))  # noqa: S311  # nosec B311
                self.stdout.write(f"demo: {made} historical applications added for the reports")
                done = True
            if not done:
                self.stdout.write("demo data present; skipped")
            return
        call_command("bootstrap_reference")
        call_command("bootstrap_roles")
        # Seeded generator: synthetic data must be reproducible; not used for security.
        rng = random.Random(1021)  # noqa: S311  # nosec B311
        self._wipe()
        with transaction.atomic():
            users = self._users()
            doctors = self._doctors(rng)
            self._practitioners(random.Random(1473))  # noqa: S311  # nosec B311
            taj = self._taj(rng, opts["members"])
            self._members(rng, taj, doctors, users)
        self._open_queue(rng, doctors, users)
        with transaction.atomic():
            self._history(random.Random(2026))  # noqa: S311  # nosec B311
        self._identity_details(random.Random(1616))  # noqa: S311  # nosec B311
        self._privacy_examples(users)
        self.stdout.write(
            self.style.SUCCESS(
                f"demo: {Member.objects.count()} members, {TajIdentity.objects.count()} TRN identities, {Doctor.objects.count()} doctors, {Application.objects.filter(status__in=Application.OPEN_STATUSES).count()} open applications"
            )
        )

    def _wipe(self):
        with connection.cursor() as cur:
            cur.execute(
                "TRUNCATE interactions_interactionnote, interactions_interaction, cards_card, members_applicationcondition, members_application, "
                "members_membercondition, members_enrolment, members_guardian, members_member, identity_trnvalidation, identity_srnissue, identity_tajidentity, "
                "doctors_doctor, doctors_nurse, doctors_councilregisterentry, core_notification, core_integrationrun, accounts_temporaryrole, privacy_datasubjectrequest, privacy_breach, "
                "privacy_retentionrun, security_securityalert, security_accesslog, security_usersession RESTART IDENTITY CASCADE"
            )
            cur.execute("ALTER SEQUENCE members_member_number_seq RESTART WITH 2000000001")
            cur.execute("ALTER SEQUENCE members_tracking_seq RESTART WITH 1")

    def _users(self):
        user_model = get_user_model()
        password = os.environ.get("DEMO_PASSWORD", DEMO_PASSWORD_DEFAULT)
        spec = [
            ("cc.walker", "Tanya", "Walker", "HWT", ["customer_care"], False),
            ("cc.brown", "Kemar", "Brown", "MBJ", ["customer_care"], False),
            ("sup.henry", "Claudette", "Henry", "HO", ["supervisor", "customer_care"], False),  # online unit, Head Office
            ("mgr.morgan", "Desmond", "Morgan", "HO", ["manager", "srn_approver", "mcj_confirmer"], False),
            ("backoffice.lee", "Natalie", "Lee", "HO", ["back_office"], True),
            ("ictadmin.james", "Rohan", "James", "HO", ["ict_admin"], True),
            ("auditor.shaw", "Gail", "Shaw", "HO", ["auditor"], True),
            ("print.reid", "Leroy", "Reid", "HWT", ["print_operator"], False),
            ("dpo.grant", "Simone", "Grant", "HO", ["dpo"], True),
        ]
        users = {}
        for username, first, last, centre, roles, staff in spec:
            user, _ = user_model.objects.update_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{username}@demo.invalid",
                    "centre": Centre.objects.get(code=centre),
                    "is_staff": staff,
                    "is_active": True,
                },
            )
            user.set_password(password)
            user.save()
            user.groups.set(Group.objects.filter(name__in=roles))
            TOTPDevice.objects.filter(user=user).delete()  # a reseed starts the MFA enrolment demo again
            StaticDevice.objects.filter(user=user).delete()
            users[username] = user
        return users

    def _address(self, rng, parish):
        return {
            "address_line1": f"{rng.randint(1, 140)} {rng.choice(STREETS)}",
            "address_line2": rng.choice(["", "", f"Suite {rng.randint(1, 12)}", f"Shop {rng.randint(1, 30)}"]),
            "town": rng.choice(TOWNS.get(parish, ["—"])),
        }

    def _identity_details(self, rng):
        """Every synthetic person gets an NIS number (one letter + six digits) and an ID document with issue and
        expiry dates; about one member in twenty has an expired ID, and two demo staff IDs need attention."""
        today = timezone.localdate()
        used = set(Member.objects.exclude(nis_number="").values_list("nis_number", flat=True))
        used |= set(Application.objects.exclude(nis_number="").values_list("nis_number", flat=True))
        letters = "ABCDEFGHJKLMNPRSTW"

        def new_nis(seed):
            n = seed
            while True:
                value = f"{letters[n % len(letters)]}{(n * 7919 + 104729) % 1000000:06d}"
                if value not in used:
                    used.add(value)
                    return value
                n += 1

        def id_doc(age):
            kind = rng.choices(["nids", "drivers", "passport", "voter"], weights=[45, 30, 15, 10])[0] if age >= 18 else "birth"
            if kind == "birth":
                return kind, f"BC{rng.randint(1000000, 9999999)}", None, None
            years = {"nids": 10, "drivers": 5, "passport": 10, "voter": 10}[kind]
            expired = rng.random() < 0.05
            expiry = today - timedelta(days=rng.randint(10, 700)) if expired else today + timedelta(days=rng.randint(5, years * 365))
            issued = (
                expiry.replace(year=expiry.year - years) if not (expiry.month == 2 and expiry.day == 29) else expiry.replace(year=expiry.year - years, day=28)
            )
            number = {
                "nids": f"{rng.randint(100000000, 999999999)}",
                "drivers": f"{rng.randint(100000000, 999999999)}",
                "passport": f"A{rng.randint(1000000, 9999999)}",
                "voter": f"{rng.randint(10000000, 99999999)}",
            }[kind]
            return kind, number, issued, expiry

        members = list(Member.objects.filter(Q(nis_number="") | Q(id_type="")))
        for m in members:
            if not m.nis_number:
                m.nis_number = new_nis(m.pk)
            if not m.id_type:
                m.id_type, m.id_number, m.id_issue_date, m.id_expiry = id_doc(m.age())
                m.id_checked_at = m.registered_at
        Member.objects.bulk_update(members, ["nis_number", "id_type", "id_number", "id_issue_date", "id_expiry", "id_checked_at"], batch_size=500)
        apps = list(Application.objects.filter(nis_number="", status__in=Application.OPEN_STATUSES))
        for a in apps:
            owner = Member.objects.filter(trn=a.trn).exclude(trn="").only("nis_number").first() if a.trn else None
            a.nis_number = owner.nis_number if owner else new_nis(1_000_000 + a.pk)
        Application.objects.bulk_update(apps, ["nis_number"], batch_size=500)
        staff_ids = {
            "cc.walker": ("nids", "204517338", -2900, 750),
            "cc.brown": ("drivers", "118204551", -1500, 320),
            "sup.henry": ("nids", "300114282", -2000, 1600),
            "mgr.morgan": ("passport", "A2210933", -1200, 2400),
            "backoffice.lee": ("nids", "187003114", -900, 2700),
            "ictadmin.james": ("drivers", "142275906", -1700, 120),
            "auditor.shaw": ("nids", "155320417", -2600, 1000),
            "print.reid": ("drivers", "176004215", -1850, -12),  # expired: shows the staff alert
            "dpo.grant": ("passport", "A1984476", -3000, 21),  # expires within 30 days
        }
        for username, (kind, number, issued, expiry) in staff_ids.items():
            get_user_model().objects.filter(username=username).update(
                id_type=kind, id_issue_date=today + timedelta(days=issued), id_expiry=today + timedelta(days=expiry)
            )
            user = get_user_model().objects.filter(username=username).first()
            if user and not user.id_number:
                user.id_number = number
                user.save(update_fields=["id_number"])
        return len(members) + len(apps)

    def _practitioners(self, rng):
        """Practice addresses, the synthetic MCJ and NCJ register copies, and a nurses register."""
        StoredImage.objects.filter(kind="practitioner_photo").delete()
        now = timezone.now()
        doctors = list(Doctor.objects.filter(status="confirmed"))
        concerns = {d.pk: s for d, s in zip(rng.sample(doctors, min(4, len(doctors))), ["lapsed", "lapsed", "suspended", "lapsed"], strict=False)}
        entries = []
        for d in doctors:
            for k, v in self._address(rng, d.parish).items():
                setattr(d, k, v)
            status = concerns.get(d.pk, "active")
            valid = date(2025, 12, 31) if status == "lapsed" else date(rng.choice([2026, 2027]), 12, 31)
            d.register_status, d.licence_valid_until = status, valid
            d.register_checked_at = now - timedelta(days=rng.randint(1, 25))
            d.verified_via = d.verified_via or "manual"
            entries.append(
                CouncilRegisterEntry(
                    council="mcj",
                    number=d.mcj_number,
                    title="Dr",
                    first_name=d.first_name,
                    last_name=d.last_name,
                    specialty=d.specialty,
                    status=status,
                    valid_until=valid,
                    source="demo",
                )
            )
        Doctor.objects.bulk_update(
            doctors, ["address_line1", "address_line2", "town", "register_status", "licence_valid_until", "register_checked_at", "verified_via"]
        )
        for i in range(40):  # registered with the MCJ but not yet in the NHF register: confirmed automatically when first used
            entries.append(
                CouncilRegisterEntry(
                    council="mcj",
                    number=str(30001 + i * 3),
                    title="Dr",
                    first_name=rng.choice(FIRST_F + FIRST_M),
                    last_name=rng.choice(LAST),
                    specialty=rng.choice(DOCTOR_SPECIALTIES),
                    status="active",
                    valid_until=date(2027, 12, 31),
                    source="demo",
                )
            )
        parishes = [c[0] for c in TOWNS.items()]
        nurses = []
        categories = ["rn"] * 6 + ["rm", "rnrm", "np", "ean", "phn", "crna"]
        for i in range(160):
            parish = rng.choice(parishes)
            cat = rng.choice(categories)
            number = str(40001 + i * 11)
            status = "lapsed" if i in (7, 93) else "active"
            valid = date(2025, 6, 30) if status == "lapsed" else date(rng.choice([2026, 2027]), 6, 30)
            first, last = rng.choice(FIRST_F + FIRST_M[:8]), rng.choice(LAST)
            workplace = self._address(rng, parish)
            if rng.random() < 0.6:  # hospital staff: the hospital's town; others at the town's health centre
                workplace["practice_name"] = HOSPITALS[parish]
            else:
                workplace["practice_name"] = f"{workplace['town']} Health Centre"
            nurses.append(
                Nurse(
                    ncj_number=number,
                    first_name=first,
                    last_name=last,
                    category=cat,
                    parish=parish,
                    phone=f"876-{rng.randint(900, 999)}-{rng.randint(1000, 9999)}",
                    status="confirmed",
                    verified_via="register",
                    confirmed_with_ncj_at=now - timedelta(days=rng.randint(30, 900)),
                    register_status=status,
                    licence_valid_until=valid,
                    register_checked_at=now - timedelta(days=rng.randint(1, 25)),
                    decision_note="Verified against the Nursing Council of Jamaica register",
                    **workplace,
                )
            )
            entries.append(
                CouncilRegisterEntry(
                    council="ncj",
                    number=number,
                    title="Nurse",
                    first_name=first,
                    last_name=last,
                    specialty=NURSE_CATEGORY_LABELS[cat],
                    status=status,
                    valid_until=valid,
                    source="demo",
                )
            )
        Nurse.objects.bulk_create(nurses)
        Nurse.objects.create(
            ncj_number="47003",
            first_name="Tricia",
            last_name="Malcolm",
            category="rn",
            status="pending",
            practice_name="Port Antonio Hospital",
            parish="POR",
            town="Port Antonio",
        )
        for council, number, title, first, last, spec, status, valid in REGISTER_DEMO:
            entries.append(
                CouncilRegisterEntry(
                    council=council,
                    number=number,
                    title=title,
                    first_name=first,
                    last_name=last,
                    specialty=spec,
                    status=status,
                    valid_until=valid,
                    source="demo",
                )
            )
        CouncilRegisterEntry.objects.bulk_create(entries, ignore_conflicts=True)

    def _doctors(self, rng):
        parishes = [c.parish for c in Centre.objects.all()]
        rows = []
        for i in range(320):
            first = rng.choice(FIRST_F + FIRST_M)
            rows.append(
                Doctor(
                    mcj_number=str(10001 + i * 7),
                    first_name=first,
                    last_name=rng.choice(LAST),
                    specialty=rng.choice(DOCTOR_SPECIALTIES),
                    practice_name=f"{rng.choice(LAST)} Medical Centre",
                    parish=rng.choice(parishes),
                    phone=f"876-{rng.randint(900, 999)}-{rng.randint(1000, 9999)}",
                    status="confirmed",
                    confirmed_with_mcj_at=timezone.now() - timedelta(days=rng.randint(30, 2000)),
                )
            )
        Doctor.objects.bulk_create(rows)
        return list(Doctor.objects.all())

    def _taj(self, rng, n_members):
        rows = [
            TajIdentity(trn=t, first_name=f, middle_name=m, last_name=last, dob=d, gender=g, address_line1=a1, address_line2=a2, parish=p, demo_note=note)
            for t, f, m, last, d, g, a1, a2, p, note in DEMO_TAJ
        ]
        used = {r.trn for r in rows}
        parishes = [c.parish for c in Centre.objects.all()]
        today = timezone.localdate()
        while len(rows) < int(n_members * 1.25):
            trn = str(rng.choice([1, 1, 1, 0])) + "".join(str(rng.randint(0, 9)) for _ in range(8))
            if trn in used or trn.startswith("9"):
                continue
            used.add(trn)
            gender = rng.choice("MF")
            age = int(min(95, max(1, rng.gauss(52, 18))))
            dob = today - timedelta(days=age * 365 + rng.randint(0, 364))
            rows.append(
                TajIdentity(
                    trn=trn,
                    first_name=(first := rng.choice(FIRST_M if gender == "M" else FIRST_F)),
                    middle_name=rng.choice([m for m in MIDDLE if m != first]) if rng.random() < 0.5 else "",
                    last_name=rng.choice(LAST),
                    dob=dob,
                    gender=gender,
                    address_line1=f"{rng.randint(1, 120)} {rng.choice(STREETS)}",
                    address_line2="",
                    parish=rng.choice(parishes),
                )
            )
        TajIdentity.objects.bulk_create(rows, batch_size=2000)
        return list(TajIdentity.objects.order_by("id"))

    def _members(self, rng, taj, doctors, users):
        centres = list(Centre.objects.all())
        conditions = list(MedicalCondition.objects.prefetch_related("programmes"))
        nhf = Programme.objects.get(code="nhf")
        jadep = Programme.objects.get(code="jadep")
        today = timezone.localdate()
        now = timezone.now()
        demo = [t for t in taj if t.trn in DEMO_MEMBERS]
        pool = [t for t in taj if not t.demo_note][: max(0, int(len(taj) / 1.25) - len(DEMO_MEMBERS))]
        chosen = demo + pool
        with connection.cursor() as cur:
            cur.execute("SELECT nextval('members_member_number_seq') FROM generate_series(1, %s)", [len(chosen)])
            numbers = [str(r[0]) for r in cur.fetchall()]
        nis_numbers = list(
            {f"{rng.choice('ACDEFGHJKLMNPRSTUVWXYZ')}{rng.randint(100000, 999999)}" for _ in range(len(chosen))}
        )  # B-series kept for the named demo case
        members = []
        for t, number in zip(chosen, numbers, strict=True):
            centre = rng.choice(centres)
            overrides = DEMO_MEMBERS.get(t.trn, {})
            registered = now - timedelta(days=rng.randint(1, 3650), minutes=rng.randint(0, 600))
            members.append(
                Member(
                    member_number=number,
                    trn=t.trn,
                    first_name=t.first_name,
                    middle_name=t.middle_name,
                    last_name=overrides.get("last_name", t.last_name),
                    dob=t.dob,
                    gender=t.gender,
                    phone_mobile=f"876-{rng.choice([3, 4, 5, 8])}{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
                    email=f"{t.first_name.lower()}.{t.last_name.lower()}{rng.randint(1, 99)}@example.com".replace("'", "") if rng.random() < 0.4 else "",
                    address_line1=t.address_line1,
                    parish=t.parish or centre.parish,
                    collection_centre=centre,
                    registered_centre=centre,
                    registered_at=registered,
                    identity_refreshed_at=registered,
                    nis_number=overrides.get("nis_number") or (nis_numbers.pop() if rng.random() < 0.65 else ""),
                    consent_at=registered,
                    consent_version="2024-01",
                )
            )
        Member.objects.bulk_create(members, batch_size=2000)
        members = list(Member.objects.order_by("id"))
        mconds, enrols, cards, interactions, guardians = [], [], [], [], []
        for m in members:
            age = m.age(today)
            eligible = [c for c in conditions if (not c.sex_restriction or c.sex_restriction == m.gender) and (c.min_age is None or age >= c.min_age)]
            picked = rng.sample(eligible, k=min(len(eligible), rng.choice([1, 1, 2, 2, 3])))
            if m.trn == "100200307":
                picked = [c for c in conditions if c.code in ("hypertension", "diabetes")]
            doctor = rng.choice(doctors)
            for c in picked:
                mconds.append(
                    MemberCondition(
                        member=m,
                        condition=c,
                        severity=rng.choice(["mild", "moderate", "moderate", "severe"]),
                        certified_by=doctor,
                        certified_on=m.registered_at.date(),
                    )
                )
            enrols.append(Enrolment(member=m, programme=nhf, enrolled_at=m.registered_at, source="migration"))
            if age >= 60 and any(jadep in c.programmes.all() for c in picked):
                enrols.append(Enrolment(member=m, programme=jadep, enrolled_at=m.registered_at, source="migration"))
            if age < 18:
                guardians.append(Guardian(member=m, full_name=f"{rng.choice(FIRST_F)} {m.last_name}", relationship="Mother", phone=m.phone_mobile))
            recent = (now - m.registered_at).days < 2
            card = Card(
                member=m, version_no=1, reason="new", centre=m.collection_centre, print_name=clean_card_name(m.full_name)[:60], queued_at=m.registered_at
            )
            card.member = m
            card.encode_tracks()
            if recent:
                card.state = "queued"
            else:
                card.state = "dispatched"
                card.printed_at = m.registered_at + timedelta(minutes=rng.randint(4, 9))
                card.verified_at = card.printed_at + timedelta(minutes=rng.randint(1, 3))
                card.dispatched_at = card.verified_at + timedelta(minutes=rng.randint(1, 4))
                card.serial_number = f"NHF{m.registered_at:%y}{rng.randint(1000000, 9999999)}"
                card.phi_reconciled_at = card.queued_at
            cards.append(card)
            interactions.append(
                Interaction(
                    at=m.registered_at,
                    member=m,
                    kind="system",
                    event="member.migrated",
                    summary=f"Registered at {m.registered_centre} (migrated record)",
                    centre=m.registered_centre,
                )
            )
        MemberCondition.objects.bulk_create(mconds, batch_size=5000)
        Enrolment.objects.bulk_create(enrols, batch_size=5000)
        Guardian.objects.bulk_create(guardians, batch_size=2000)
        Card.objects.bulk_create(cards, batch_size=2000)
        Interaction.objects.bulk_create(interactions, batch_size=5000)

    def _privacy_examples(self, users):
        """One open access request and one contained breach, so the Data Protection screens are not empty."""
        from apps.privacy.models import Breach, DataSubjectRequest

        now = timezone.now()
        lewis = Member.objects.filter(trn="100200307").first()
        DataSubjectRequest.objects.create(
            member=lewis,
            requester_name=lewis.full_name if lewis else "Andre Lewis",
            requester_contact=lewis.phone_mobile if lewis else "",
            identity_checked=True,
            kind="access",
            channel="counter",
            details="Asked at the Union Square counter for a copy of everything the Fund holds about him.",
            received_at=now - timedelta(days=3),
            due_at=now - timedelta(days=3) + timedelta(days=30),
            logged_by=users["cc.walker"],
        )
        Breach.objects.create(
            title="Application status e-mail sent to the wrong address (demonstration record)",
            discovered_at=now - timedelta(hours=20),
            occurred_at=now - timedelta(hours=26),
            description="A status e-mail for one applicant was sent to a mistyped address. Synthetic example for the demonstration.",
            data_categories="Name, tracking number",
            subjects_affected=1,
            severity="low",
            status="contained",
            contained_at=now - timedelta(hours=18),
            actions="Recipient asked to delete the message; address corrected on the record.",
            logged_by=users["dpo.grant"],
        )

    def _history(self, rng):
        """A year of decided applications behind the members, so the reports and dashboard have something to show.

        Walk-ins mostly inside the 15-minute target, online forms over hours, mailed forms over days; rejections with
        reasons; change forms (medical updates, contact changes, replacement cards) and a few repeat replacements.
        """
        from apps.rules.models import RejectionReason

        now = timezone.now()
        year_ago = now - timedelta(days=365)
        users = get_user_model()
        staff = {u.centre_id: u for u in users.objects.filter(groups__name="customer_care").select_related("centre") if u.centre_id}
        any_staff = list(staff.values()) or [None]
        ho = Centre.objects.filter(code="HO").first()
        doctors = list(Doctor.objects.filter(status="confirmed").values_list("mcj_number", flat=True)[:200]) or [""]
        reasons = {r.code: r for r in RejectionReason.objects.all()}
        weights = [("walk_in", 62), ("online", 24), ("mail", 7), ("email", 5), ("batch", 2)]
        channels = [c for c, w in weights for _ in range(w)]

        def wait(channel):
            if channel == "walk_in":
                return timedelta(minutes=max(4, rng.gauss(12, 5)) if rng.random() < 0.86 else rng.uniform(16, 55))
            if channel == "online":
                return timedelta(hours=rng.uniform(0.5, 30))
            if channel == "mail":
                return timedelta(days=rng.uniform(2, 9))
            if channel == "email":
                return timedelta(hours=rng.uniform(2, 40))
            return timedelta(days=rng.uniform(1, 5))

        members = list(Member.objects.filter(registered_at__gte=year_ago, applications__isnull=True).select_related("registered_centre"))
        apps, made = [], 0

        def tracking(when):
            with connection.cursor() as cur:
                cur.execute("SELECT nextval('members_tracking_seq')")
                return f"NHF-A-{timezone.localtime(when).year}-{cur.fetchone()[0]:07d}"

        def base(m, channel, received, decided, status, kind="new", **extra):
            centre = ho if channel == "online" and ho else m.registered_centre
            who = staff.get(centre.pk) or rng.choice(any_staff)
            return Application(
                tracking_number=tracking(received),
                kind=kind,
                channel=channel,
                centre=centre,
                received_at=received,
                entered_by=who,
                status=status,
                member=m if status == "approved" else None,
                trn=m.trn,
                identity_confirmed=True,
                form_first_name=m.first_name,
                form_last_name=m.last_name,
                form_dob=m.dob,
                first_name=m.first_name,
                last_name=m.last_name,
                dob=m.dob,
                gender=m.gender,
                parish=m.parish,
                address_line1=m.address_line1,
                phone_mobile=m.phone_mobile,
                collection_centre=m.collection_centre,
                doctor_mcj=rng.choice(doctors),
                declaration_signed=True,
                doctor_signed=True,
                consent_given=True,
                consent_at=received,
                consent_version="2026-11",
                decided_at=decided,
                decided_by=who,
                **extra,
            )

        for m in members:
            channel = rng.choice(channels)
            received = m.registered_at - wait(channel)
            apps.append(base(m, channel, received, m.registered_at, "approved"))
        # Rejections: people who applied and were turned down (not members).
        spare = list(TajIdentity.objects.filter(demo_note="").exclude(trn__in=Member.objects.values("trn"))[:120])
        reason_mix = (
            ["incomplete_form"] * 5
            + ["not_certified"] * 3
            + ["trn_mismatch"] * 3
            + ["duplicate_application"] * 2
            + ["doctor_unconfirmed", "not_eligible", "guardian_missing"]
        )
        for t in spare[:90]:
            channel = rng.choice(channels)
            received = year_ago + timedelta(seconds=rng.randint(0, 365 * 86400 - 3600))
            fake = Member(trn=t.trn, first_name=t.first_name, last_name=t.last_name, dob=t.dob, gender=t.gender, parish=t.parish or "KGN")
            fake.registered_centre = rng.choice(list(Centre.objects.filter(is_active=True)))
            fake.collection_centre = fake.registered_centre
            reason = reasons.get(rng.choice(reason_mix))
            apps.append(base(fake, channel, received, received + wait(channel), "rejected", rejection_reason=reason))
        # Change forms from existing members.
        old = list(Member.objects.filter(registered_at__lt=year_ago).select_related("registered_centre", "collection_centre").order_by("?")[:420])
        replacements = []
        for i, m in enumerate(old):
            roll = 0.85 if i < 6 else rng.random()  # the first few always replace a card (repeat-replacement examples)
            channel = "online" if roll < 0.45 and rng.random() < 0.6 else rng.choice(["walk_in", "walk_in", "walk_in", "email"])
            received = year_ago + timedelta(seconds=rng.randint(0, 365 * 86400 - 3600))
            flags = {}
            if roll < 0.45:
                flags["change_conditions"] = True
            elif roll < 0.75:
                flags["change_contact"] = True
            elif roll < 0.95:
                flags["reprint_reason"] = "replacement"
                replacements.append((m, received))
                if i < 6:  # a few members who lose cards repeatedly
                    for k in (1, 2):
                        again = received + timedelta(days=30 * k + rng.randint(0, 20))
                        if again < now:
                            apps.append(base(m, "walk_in", again, again + wait("walk_in"), "approved", kind="change", reprint_reason="replacement"))
                            replacements.append((m, again))
            else:
                flags["change_guardian"] = True
            apps.append(base(m, channel, received, received + wait(channel), "approved", kind="change", **flags))
        Application.objects.bulk_create(apps, batch_size=1000)
        made = len(apps)
        # Replacement cards and the interaction log for the history.
        versions = {}
        cards = []
        for m, when in sorted(replacements, key=lambda x: x[1]):
            v = versions.get(m.pk) or (m.cards.order_by("-version_no").values_list("version_no", flat=True).first() or 1)
            v += 1
            versions[m.pk] = v
            card = Card(member=m, version_no=v, reason="replacement", centre=m.collection_centre, print_name=clean_card_name(m.full_name)[:60], queued_at=when)
            card.encode_tracks()
            card.state = "dispatched"
            card.printed_at = when + timedelta(minutes=rng.randint(4, 9))
            card.verified_at = card.printed_at + timedelta(minutes=2)
            card.dispatched_at = card.verified_at + timedelta(minutes=2)
            card.serial_number = f"NHF{when:%y}{rng.randint(1000000, 9999999)}"
            card.phi_reconciled_at = when
            cards.append(card)
        Card.objects.bulk_create(cards, batch_size=1000)
        kinds = {"walk_in": "visit", "online": "system", "mail": "note", "email": "email", "batch": "note"}
        Interaction.objects.bulk_create(
            [
                Interaction(
                    at=a.decided_at,
                    member=a.member,
                    application=a,
                    kind=kinds.get(a.channel, "note"),
                    event=f"application.{a.status}",
                    summary=f"{a.get_kind_display()} {a.tracking_number} {a.status}",
                    actor=a.decided_by,
                    centre=a.centre,
                )
                for a in Application.objects.filter(tracking_number__in=[x.tracking_number for x in apps])
            ],
            batch_size=1000,
        )
        return made

    def _open_queue(self, rng, doctors, users):
        """Work in progress so the queues and dashboards are not empty."""
        from apps.intake.services import receive_portal_submission
        from apps.members import services

        centres = {c.code: c for c in Centre.objects.all()}
        spare = list(TajIdentity.objects.filter(demo_note="").exclude(trn__in=Member.objects.values("trn"))[:40])
        conds = list(MedicalCondition.objects.filter(code__in=["hypertension", "diabetes", "asthma", "arthritis", "glaucoma"]))
        now = timezone.now()
        for i, t in enumerate(spare[:14]):
            user = users["cc.walker"] if i % 2 else users["cc.brown"]
            app = services.start_application(
                user=user,
                centre=user.centre,
                channel=rng.choice(["walk_in", "walk_in", "walk_in", "mail", "email", "batch"]),
                received_at=now - timedelta(minutes=rng.randint(5, 600)),
                trn=t.trn,
                form_first_name=t.first_name,
                form_last_name=t.last_name,
                form_dob=t.dob,
            )
            app.refresh_from_db()
            app.phone_mobile = f"876-{rng.randint(300, 899)}-{rng.randint(1000, 9999)}"
            doctor = rng.choice(doctors)
            app.doctor, app.doctor_mcj = doctor, doctor.mcj_number
            app.collection_centre = app.centre
            # As keyed from a complete paper form (rev. 12): serial, address, signatures, Section C details.
            app.form_serial = str(9794000 + i * 7 + rng.randint(0, 6))
            app.address_line1, app.address_line2, app.parish = t.address_line1, t.address_line2, t.parish
            app.declaration_signed, app.declaration_date = True, timezone.localdate(app.received_at)
            app.trn_copy_attached = app.channel == "mail"
            app.doctor_signed, app.certified_on, app.conditions_total = True, timezone.localdate(app.received_at) - timedelta(days=rng.randint(1, 20)), 1
            app.doctor_office_address, app.doctor_parish = doctor.address_line1, app.parish
            app.save()
            if i % 3:
                services.set_conditions(app, [(rng.choice(conds), rng.choice(["mild", "mild", "severe"]))])
                app.consent_given, app.consent_at, app.consent_version = True, timezone.now(), "2026-10"
                app.save(update_fields=["consent_given", "consent_at", "consent_version"])
            services.refresh_status(app)
        for i, t in enumerate(spare[14:24]):
            doctor = rng.choice(doctors)
            receive_portal_submission(
                {
                    "reference": f"DP-{now:%y%m%d}-{i + 1:04d}",
                    "kind": "new",
                    "patient": {
                        "trn": t.trn,
                        "first_name": t.first_name,
                        "last_name": t.last_name,
                        "dob": t.dob.isoformat(),
                        "mobile": f"876-{rng.randint(300, 899)}-{rng.randint(1000, 9999)}",
                    },
                    "doctor": {"mcj_number": doctor.mcj_number, "name": f"Dr {doctor.first_name} {doctor.last_name}"},
                    "conditions": [rng.choice(conds).code],
                    "consent": True,
                }
            )
        existing = list(Member.objects.exclude(trn__in=[d[0] for d in DEMO_TAJ]).order_by("?")[:3])
        for i, m in enumerate(existing):
            doctor = rng.choice(doctors)
            receive_portal_submission(
                {
                    "reference": f"DP-{now:%y%m%d}-C{i + 1:03d}",
                    "kind": "change",
                    "patient": {"trn": m.trn, "first_name": m.first_name, "last_name": m.last_name, "dob": m.dob.isoformat(), "mobile": m.phone_mobile},
                    "doctor": {"mcj_number": doctor.mcj_number, "name": f"Dr {doctor.first_name} {doctor.last_name}"},
                    "conditions": [rng.choice(conds).code],
                    "consent": True,
                }
            )
        # One online application from an unknown doctor (MCJ confirmation queue)
        t = spare[24]
        receive_portal_submission(
            {
                "reference": f"DP-{now:%y%m%d}-U001",
                "kind": "new",
                "patient": {"trn": t.trn, "first_name": t.first_name, "last_name": t.last_name, "dob": t.dob.isoformat(), "mobile": "876-555-0101"},
                "doctor": {"mcj_number": "99901", "name": "Dr Simone Barrett"},
                "conditions": ["hypertension"],
                "consent": True,
            }
        )
        # Spread the open walk-ins over centres for the dashboard
        Application.objects.filter(status__in=Application.OPEN_STATUSES, channel="batch").update(centre=centres["SPT"])
