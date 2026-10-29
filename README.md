# FCC Registry Platform — Member Registration (NHF)

Member Registration System for the National Health Fund — RFB No. NHF/MRS/2026-09 (GoJEP 1021/1473).
It replaces NHF's Member Registration application and folds the TRN Validator, Card Verification and NHF Dispatch
systems into one platform, with ID Works kept as an integrated card-production system.

Design reference: `NHF 1021-1473/02_Design Plan/20_NHF_MRS_Design_and_Build_Plan.pdf` (sections 4–9, 14–15).

**Status: v0.1.0 — Phase A sprints A0 (scaffold) and A1 (counter journey).** The three demonstration use cases NHF
names — TRN validation, rule-enforced data entry, interaction logging — run end to end. Card printing, swipe
verification and dispatch (A2) and dashboards, documents and scanning (A3) follow. See `docs/requirements-coverage.md`.

## Modules

| Module | App | What it does now |
|---|---|---|
| Registry Core | `core`, `accounts` | Roles (global, process-specific, temporary), TOTP MFA, lockout, idle timeout, append-only audit, parameters, notifications, Integration Hub run log |
| Members | `members` | New and change forms, all channels, tracking numbers, member numbers, contact edits, rejection, tracking search |
| Rules | `rules` | Programmes, benefits, conditions and rejection reasons configured in the back office; guardian under 18, JADEP at 60, clinical consistency |
| Identity Verification | `identity` | TRN adapter (mock now, SOAP client ready), match/mismatch, outage circuit breaker, SRN with manager approval and duplicate check, screening |
| Doctors | `doctors` | NHF Doctors register, MCJ confirmation workflow, rejection on non-confirmation |
| Online Intake | `intake`, `api` | Signed doctor-portal endpoint, online queue, change-form flag, "being worked by" locks, assignment |
| Card Services | `cards` | Card versions, ISO 7811 track strings, print queue (print/verify/dispatch in A2) |
| Interactions | `interactions` | Append-only log of every event and contact, with notes |

## Stack

Python 3.12 · Django 5.2 LTS · PostgreSQL 16 · Celery 5 (+ Redis 7 when present) · HTMX 2 + Tailwind CSS v4 (compiled) ·
Django REST Framework + drf-spectacular · django-otp · django-axes · django-csp · Gunicorn · Docker.

Name, date of birth, gender and TRN on a member row are locked by a PostgreSQL trigger: only the Identity
Verification module can change them, inside a transaction that applies a TRN-service payload. Audit and interaction
tables refuse UPDATE and DELETE in the database.

## Local development

```bash
cp .env.example .env
docker compose up -d db                 # or any PostgreSQL 16
pip install -r requirements-dev.txt
npm install && npm run build            # compiles Tailwind and copies htmx into static/; commit the output
python manage.py migrate
python manage.py bootstrap_roles && python manage.py bootstrap_reference
python manage.py seed_demo_data --force # synthetic: 5,000 members, 21 centres, demo users
python manage.py runserver
pytest                                  # needs PostgreSQL (triggers, sequences)
```

Without `REDIS_URL` the app runs single-process: tasks run inline and sessions use the database. With Redis, run
`scripts/entrypoint.sh worker` and `scripts/entrypoint.sh beat` beside the web process.

## Railway staging (demonstration environment)

One service from this repository plus a PostgreSQL database. Variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `FIELD_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DEMO_MODE` | `1` |
| `DEMO_DATA` | `1` (seed once) — `reseed` rebuilds the demo data on the next deploy |
| `DEMO_PASSWORD` | password for the demo users |
| `PORTAL_SHARED_SECRET` | any long random string |

The entrypoint migrates, loads roles and reference data, seeds the demo set, then starts Gunicorn. Railway's public
domain is trusted automatically. Health check: `/healthz`.

## Demo users (synthetic data only)

| Username | Role | Use it for |
|---|---|---|
| `cc.walker` | Customer Care, Half-Way-Tree | Counter journey |
| `cc.brown` | Customer Care, Montego Bay | Second agent (work locks) |
| `sup.henry` | Supervisor + Customer Care | Online queue assignment |
| `mgr.morgan` | Manager, SRN approver, MCJ confirmer | SRN approval, MCJ confirmations, temporary roles — MFA enrolment on first sign-in |
| `backoffice.lee` | Back-office power user | Programmes, benefits, conditions (`/backoffice/`) |
| `ictadmin.james` | Application administrator | Users and roles — MFA on first sign-in, no member access |
| `auditor.shaw` | Auditor | Read-only, conditions masked, audit trail |
| `print.reid` | Card print operator | Print queue |

Demonstration cases are in `docs/demo-script.md`.
