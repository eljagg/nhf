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
from django.utils import timezone
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.cards.models import Card, clean_card_name
from apps.core.models import Centre
from apps.doctors.models import Doctor
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


class Command(BaseCommand):
    help = "Seed synthetic demonstration data (requires --force)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--if-missing", action="store_true", help="Skip when demo data is already present.")
        parser.add_argument("--members", type=int, default=5000)

    def handle(self, *args, **opts):
        if not opts["force"]:
            raise CommandError("Refusing to seed without --force (synthetic data; never on production).")
        if opts["if_missing"] and TajIdentity.objects.exists():
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
            taj = self._taj(rng, opts["members"])
            self._members(rng, taj, doctors, users)
        self._open_queue(rng, doctors, users)
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
                "doctors_doctor, core_notification, core_integrationrun, accounts_temporaryrole, privacy_datasubjectrequest, privacy_breach, "
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
            ("sup.henry", "Claudette", "Henry", "HWT", ["supervisor", "customer_care"], False),
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
            users[username] = user
        return users

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
            details="Asked at the Half-Way-Tree counter for a copy of everything the Fund holds about him.",
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
                channel=rng.choice(["walk_in", "walk_in", "email", "batch"]),
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
            app.save()
            if i % 3:
                services.set_conditions(app, [(rng.choice(conds), "moderate")])
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
