"""Shared fixtures: reference data, role users, synthetic TRN identities, doctors."""

from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from apps.core.models import Centre
from apps.doctors.models import Doctor
from apps.identity.models import TajIdentity

PASSWORD = "Test-Password-2026!"  # noqa: S105


@pytest.fixture(autouse=True)
def reference(db):
    """Reference data and role groups for every test."""
    call_command("bootstrap_reference", verbosity=0)
    call_command("bootstrap_roles", verbosity=0)


@pytest.fixture
def centre(reference):
    return Centre.objects.get(code="HWT")


def make_user(username, *roles, centre=None):
    user = get_user_model().objects.create_user(
        username=username, password=PASSWORD, first_name=username.split(".")[-1].title(), email=f"{username}@test.invalid", centre=centre
    )
    user.groups.set(Group.objects.filter(name__in=roles))
    return user


@pytest.fixture
def agent(centre):
    return make_user("cc.agent", "customer_care", centre=centre)


@pytest.fixture
def agent2(centre):
    return make_user("cc.second", "customer_care", centre=centre)


@pytest.fixture
def manager(centre):
    return make_user("mgr.boss", "manager", "srn_approver", "mcj_confirmer", centre=centre)


@pytest.fixture
def auditor(centre):
    return make_user("aud.it", "auditor", centre=centre)


@pytest.fixture
def ict(centre):
    return make_user("ict.admin", "ict_admin", centre=centre)


@pytest.fixture
def taj(reference):
    rows = {
        "adult": TajIdentity.objects.create(
            trn="100200301",
            first_name="Marcia",
            middle_name="Angela",
            last_name="Campbell",
            dob=date(1979, 3, 14),
            gender="F",
            address_line1="12 Hope Road",
            parish="AND",
        ),
        "minor": TajIdentity.objects.create(trn="100200302", first_name="Tyrese", last_name="Brown", dob=date(2014, 7, 2), gender="M"),
        "senior": TajIdentity.objects.create(
            trn="100200303", first_name="Winston", middle_name="Delroy", last_name="Grant", dob=date(1958, 11, 20), gender="M"
        ),
        "female": TajIdentity.objects.create(trn="100200305", first_name="Paulette", last_name="Reid", dob=date(1972, 9, 1), gender="F"),
        "renamed": TajIdentity.objects.create(trn="100200306", first_name="Kerry-Ann", last_name="Thompson-Clarke", dob=date(1985, 1, 23), gender="F"),
    }
    return rows


@pytest.fixture
def doctor(reference):
    return Doctor.objects.create(mcj_number="10001", first_name="Kevin", last_name="Spence", status="confirmed")


@pytest.fixture
def run_commits(django_capture_on_commit_callbacks):
    """Run on_commit callbacks (TRN worker, notifications) inline, as the eager Celery setup does in Phase A."""

    def runner():
        return django_capture_on_commit_callbacks(execute=True)

    return runner
