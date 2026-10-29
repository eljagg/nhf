# Changelog

## v0.1.0 — 29 October 2026 — Phase A sprints A0 and A1

First release of the NHF Member Registration edition of the FCC Registry Platform, built from the TOR, the two
requirement workbooks and the Design and Build Plan v1.0.

- Scaffold: Django 5.2 / PostgreSQL 16 / Celery / HTMX + Tailwind v4, Docker image, Railway config, CI (ruff, bandit, pip-audit, tests, deploy checks).
- Registry Core: role catalogue with process-specific and temporary roles, TOTP MFA for manager and admin roles, lockout, idle timeout, append-only audit (database-enforced), parameters, notifications, Integration Hub run log.
- Members: new and change forms on every channel, tracking and member-number sequences, approval in one transaction (member, conditions, guardian, enrolments, queued card, interaction, audit, PHI after commit), rejection with configurable reasons, contact edits without an application, tracking search.
- Identity Verification: TRN adapter interface with mock and SOAP implementations, field-by-field match, terminate on mismatch, invalid-TRN SMS, outage circuit breaker, SRN request/approval with duplicate check, screening; protected identity fields locked by a database trigger.
- Rules: guardian under 18, JADEP at 60, sex/age clinical consistency, reprint rules; programmes, benefits, conditions and reasons configurable in the back office.
- Doctors: register, MCJ confirmation queue, automatic rejection when the Council cannot confirm.
- Online Intake: HMAC-signed portal endpoint, online queue with change-form flag, worked-by locks with heartbeat, supervisor assignment, portal simulator for the demonstration.
- Card Services: card versions with ISO 7811 tracks and the print queue.
- Synthetic demonstration data: 5,000 members, 21 centres, 320 doctors, named demo cases, eight demo users.
- 36 tests on PostgreSQL.
