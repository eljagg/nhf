"""TRN service adapters (Integration Hub). The interface is the same for the mock and the SOAP client (IN10002, IN10004)."""

import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from apps.core.models import IntegrationRun, Parameter

log = logging.getLogger(__name__)

BREAKER_KEY = "trn-breaker-failures"
BREAKER_THRESHOLD = 3
BREAKER_SECONDS = 60


class ServiceUnavailable(Exception):
    """The TRN service could not be reached or timed out."""


@dataclass
class TrnResult:
    """What the service returned."""

    found: bool
    identity: dict | None = None


class TrnAdapter:
    """Base adapter with run logging and a circuit breaker."""

    name = "base"

    def _lookup(self, trn: str) -> TrnResult:
        raise NotImplementedError

    def lookup(self, trn: str) -> TrnResult:
        """Call the service; raises ServiceUnavailable on failure or while the breaker is open."""
        if (cache.get(BREAKER_KEY) or 0) >= BREAKER_THRESHOLD:
            IntegrationRun.objects.create(system="trn", operation="validate", adapter=self.name, ok=False, reference=trn, message="circuit open")
            raise ServiceUnavailable("TRN service unavailable (circuit open) — issue an SRN or defer the application.")
        started = time.monotonic()
        try:
            result = self._lookup(trn)
        except ServiceUnavailable as exc:
            failures = (cache.get(BREAKER_KEY) or 0) + 1
            cache.set(BREAKER_KEY, failures, BREAKER_SECONDS)
            IntegrationRun.objects.create(
                system="trn",
                operation="validate",
                adapter=self.name,
                ok=False,
                duration_ms=int((time.monotonic() - started) * 1000),
                reference=trn,
                message=str(exc)[:300],
            )
            raise
        cache.delete(BREAKER_KEY)
        IntegrationRun.objects.create(
            system="trn",
            operation="validate",
            adapter=self.name,
            ok=True,
            duration_ms=int((time.monotonic() - started) * 1000),
            reference=trn,
            message="found" if result.found else "not found",
        )
        return result


class MockTrnAdapter(TrnAdapter):
    """Reads the synthetic TAJ register. Back office can switch it 'down' to demonstrate the outage path."""

    name = "mock"

    def _lookup(self, trn):
        from .models import TajIdentity

        if Parameter.get("mock-trn-service-down", False):
            raise ServiceUnavailable("TRN service did not respond within the timeout.")
        row = TajIdentity.objects.filter(trn=trn).first()
        if row is None:
            return TrnResult(found=False)
        return TrnResult(
            found=True,
            identity={
                "trn": row.trn,
                "first_name": row.first_name,
                "middle_name": row.middle_name,
                "last_name": row.last_name,
                "dob": row.dob.isoformat(),
                "gender": row.gender,
                "address_line1": row.address_line1,
                "address_line2": row.address_line2,
                "parish": row.parish,
            },
        )


class SoapTrnAdapter(TrnAdapter):
    """SOAP client to the TRN Validation Web Service through the ICT Authority.

    The WSDL, operation name and WS-Security profile are supplied by NHF/ICTA at inception;
    this class is wired to them in Phase B sprint B2. Requires ``zeep`` (requirements-integrations.txt).
    """

    name = "soap"

    def _lookup(self, trn):
        try:
            from zeep import Client, Settings
            from zeep.transports import Transport
            from zeep.wsse.username import UsernameToken
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ServiceUnavailable("zeep is not installed") from exc
        cfg = settings.TRN_SOAP
        if not cfg["WSDL"]:
            raise ServiceUnavailable("TRN_SOAP_WSDL is not configured")
        try:
            client = Client(
                cfg["WSDL"], wsse=UsernameToken(cfg["USERNAME"], cfg["PASSWORD"]), transport=Transport(timeout=cfg["TIMEOUT"]), settings=Settings(strict=False)
            )
            reply = client.service.ValidateTRN(trn)  # operation name confirmed against the WSDL at inception
        except Exception as exc:  # noqa: BLE001 - any transport/SOAP fault is an outage for the counter
            raise ServiceUnavailable(f"TRN service error: {exc}") from exc
        if not reply or not getattr(reply, "IsValid", False):
            return TrnResult(found=False)
        return TrnResult(
            found=True,
            identity={
                "trn": trn,
                "first_name": getattr(reply, "FirstName", ""),
                "middle_name": getattr(reply, "MiddleName", "") or "",
                "last_name": getattr(reply, "LastName", ""),
                "dob": str(getattr(reply, "DateOfBirth", "")),
                "gender": getattr(reply, "Gender", ""),
                "address_line1": getattr(reply, "AddressLine1", "") or "",
                "address_line2": getattr(reply, "AddressLine2", "") or "",
                "parish": getattr(reply, "Parish", "") or "",
            },
        )


def get_adapter() -> TrnAdapter:
    """Adapter selected by TRN_ADAPTER."""
    return SoapTrnAdapter() if settings.TRN_ADAPTER == "soap" else MockTrnAdapter()
