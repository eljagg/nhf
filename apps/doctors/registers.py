"""Council register connectors: Medical Council of Jamaica (doctors) and Nursing Council of Jamaica (nurses).

Neither council publishes a machine-readable register today, so two adapters share one interface:

* ``local``  — checks the local copy of the register (CouncilRegisterEntry), loaded from the extract the council
  supplies (CSV import screen) and refreshed whenever a new extract arrives. Synthetic rows in the demo.
* ``https``  — calls the council's verification service once a data-sharing agreement provides one:
  GET {URL with {number}} with an API key header, JSON reply. 404 means "not on the register".

Every check is written to the Integration Hub log. Three failures in a row open a circuit for a minute so a slow
council service does not hold up the counter; the practitioner simply waits in the manual confirmation queue.
"""

import logging
import time
from dataclasses import dataclass
from datetime import date

import requests
from django.conf import settings
from django.core.cache import cache

from apps.core.models import IntegrationRun

from .models import COUNCILS, CouncilRegisterEntry

log = logging.getLogger(__name__)
BREAKER_THRESHOLD = 3
BREAKER_SECONDS = 60
COUNCIL_NAMES = dict(COUNCILS)


class RegisterUnavailable(Exception):
    """The council register could not be checked just now."""


@dataclass
class RegisterResult:
    """What the register says about one registration number."""

    found: bool
    number: str
    status: str = "not_found"  # active | lapsed | suspended | removed | not_found
    title: str = ""
    first_name: str = ""
    last_name: str = ""
    specialty: str = ""
    valid_until: date | None = None

    @property
    def in_good_standing(self):
        return self.found and self.status == "active" and (self.valid_until is None or self.valid_until >= date.today())


def _cfg(council):
    return settings.PRACTITIONER_REGISTERS[council]


class RegisterAdapter:
    """Run logging and circuit breaker around one council's lookup."""

    name = "base"

    def __init__(self, council):
        self.council = council

    def _lookup(self, number) -> RegisterResult:
        raise NotImplementedError

    def lookup(self, number) -> RegisterResult:
        key = f"register-breaker:{self.council}"
        if (cache.get(key) or 0) >= BREAKER_THRESHOLD:
            IntegrationRun.objects.create(system=self.council, operation="verify", adapter=self.name, ok=False, reference=number, message="circuit open")
            raise RegisterUnavailable(f"{COUNCIL_NAMES[self.council]} register unavailable (circuit open).")
        started = time.monotonic()
        try:
            result = self._lookup(number)
        except RegisterUnavailable as exc:
            cache.set(key, (cache.get(key) or 0) + 1, BREAKER_SECONDS)
            IntegrationRun.objects.create(
                system=self.council,
                operation="verify",
                adapter=self.name,
                ok=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                reference=number,
                message=str(exc)[:300],
            )
            raise
        cache.delete(key)
        IntegrationRun.objects.create(
            system=self.council,
            operation="verify",
            adapter=self.name,
            ok=True,
            duration_ms=int((time.monotonic() - started) * 1000),
            reference=number,
            message=result.status,
        )
        return result


class LocalRegisterAdapter(RegisterAdapter):
    """Local copy of the council register."""

    name = "local"

    def _lookup(self, number):
        if _cfg(self.council).get("SIMULATE_DOWN"):
            raise RegisterUnavailable("Register did not respond within the timeout.")
        row = CouncilRegisterEntry.objects.filter(council=self.council, number=number).first()
        if row is None:
            return RegisterResult(found=False, number=number)
        return RegisterResult(
            found=True,
            number=number,
            status=row.status,
            title=row.title,
            first_name=row.first_name,
            last_name=row.last_name,
            specialty=row.specialty,
            valid_until=row.valid_until,
        )


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


STATUS_WORDS = {
    "active": "active",
    "registered": "active",
    "current": "active",
    "good standing": "active",
    "valid": "active",
    "lapsed": "lapsed",
    "expired": "lapsed",
    "not renewed": "lapsed",
    "suspended": "suspended",
    "removed": "removed",
    "struck off": "removed",
    "erased": "removed",
    "deregistered": "removed",
}


def normalise_status(value):
    """Map a council's wording to our five statuses."""
    return STATUS_WORDS.get(str(value or "").strip().lower(), "active" if value in (True, "true", "True") else "suspended" if value else "active")


class HttpsRegisterAdapter(RegisterAdapter):
    """The council's verification service (JSON over HTTPS)."""

    name = "https"

    def _lookup(self, number):
        cfg = _cfg(self.council)
        url = cfg["URL"]
        if not url.startswith("https://"):
            raise RegisterUnavailable("The council register URL must use https://.")
        headers = {"Accept": "application/json"}
        if cfg["API_KEY"]:
            headers[cfg["API_KEY_HEADER"]] = cfg["API_KEY"]
        try:
            resp = requests.get(url.format(number=number), headers=headers, timeout=cfg["TIMEOUT"])  # nosec B113 - timeout comes from settings (default 6 s)
        except requests.RequestException as exc:
            raise RegisterUnavailable(f"Register unreachable: {exc.__class__.__name__}") from exc
        if resp.status_code == 404:
            return RegisterResult(found=False, number=number)
        if resp.status_code != 200:
            raise RegisterUnavailable(f"Register answered {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise RegisterUnavailable("Register reply was not JSON") from exc
        body = body.get("data", body) if isinstance(body, dict) else {}
        if not body or body.get("found") is False:
            return RegisterResult(found=False, number=number)
        return RegisterResult(
            found=True,
            number=number,
            status=normalise_status(body.get("status", "active")),
            title=str(body.get("title", "") or ""),
            first_name=str(body.get("first_name") or body.get("firstName") or ""),
            last_name=str(body.get("last_name") or body.get("lastName") or body.get("surname") or ""),
            specialty=str(body.get("specialty") or body.get("category") or ""),
            valid_until=_parse_date(body.get("valid_until") or body.get("expiry_date") or body.get("expiryDate")),
        )


def get_adapter(council) -> RegisterAdapter:
    """Adapter selected by MCJ_REGISTER_MODE / NCJ_REGISTER_MODE."""
    return HttpsRegisterAdapter(council) if _cfg(council)["MODE"] == "https" else LocalRegisterAdapter(council)


def register_summary():
    """Mode and size of each council register, for the confirmations page."""
    rows = []
    for code, name in COUNCILS:
        cfg = _cfg(code)
        latest = CouncilRegisterEntry.objects.filter(council=code).order_by("-imported_at").first()
        rows.append(
            {
                "code": code,
                "name": name,
                "mode": cfg["MODE"],
                "entries": CouncilRegisterEntry.objects.filter(council=code).count(),
                "updated": latest.imported_at if latest else None,
                "demo": bool(latest and latest.source == "demo"),
            }
        )
    return rows
