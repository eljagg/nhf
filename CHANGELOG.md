# Changelog

## v0.1.2 — 29 October 2026

- Sign-in bars 40% narrower (20% → 12% of the bar area each); lettering and corner radius scaled to suit; shimmer re-aligned to the new positions.

## v0.1.1 — 29 October 2026 — sign-in redesign

- Sign-in, two-step setup, code entry and account-locked screens rebuilt: frosted-glass card over a slow-moving background, with black, gold and green bars reading "Jamaica, Land We Love" and a light shimmer that sweeps right to left and back. The shimmer is off for anyone who has turned off animations.
- Username and password boxes: brighter 2px borders, gold focus ring.
- Inside the app: frosted top bar, softer cards, small hover lift on the home counters; working forms unchanged.
- Product name and builder credit are now settings (`PRODUCT_NAME`, default "Registry Platform"; `BUILT_BY`, empty by default) — no company name is hard-coded.
- `.gitattributes` keeps LF line endings in the repository (no more CRLF warnings on Windows).
- Demo reseed also clears temporary role grants; synthetic names no longer repeat the first name as the middle name.

## v0.1.0 — 29 October 2026 — Phase A sprints A0 and A1

First release of the NHF Member Registration System, built from the TOR, the two
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
