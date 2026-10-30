# Changelog

## v0.2.5 — 29 October 2026 — build fix

- Fixed: the Docker image build failed at `collectstatic` because the production check for `FIELD_ENCRYPTION_KEY` (added in v0.2.3) also ran during the build, where hosting variables are not available. The check now runs when the app starts, not while the image is built. A test runs the Dockerfile's build command with no variables so this cannot return.
- Dockerfile header no longer names a company.

## v0.2.4 — 29 October 2026 — cleaner logs and error pages

- Friendly pages for "not part of your role" (403), "not found" (404) and server errors (500), inside the app with a way back, instead of Django's bare text.
- Logs: informational lines go to stdout and only warnings and errors to stderr, so the Railway log shows `[err]` for real problems only. Refused (403) and missing (404) pages are no longer logged with a traceback; they remain in the access log. Axes and gunicorn start-up chatter removed.
- Link scanners that fetch `/accounts/login/%3Fnext=/` (with the `?` encoded) are redirected to the sign-in page instead of getting a 404.

## v0.2.3 — 29 October 2026 — security review fixes, Active Directory state followed in-session, Data Protection Act additions

Security (independent code review; every finding has a regression test):
- **Fixed: second factor could be bypassed** by opening the enrolment page with a stolen password. Anyone who already has an authenticator must now pass the code check before enrolling or replacing one.
- **Separation of duties**: nobody can grant themselves a temporary role; managers grant only counter and back-office roles, administrators only back-office; privileged roles are never granted temporarily. In the back office nobody edits their own account, only a superuser can change superuser status, permissions, or the e-mail and password of a privileged account; role and flag changes are audited.
- E-mail of privileged accounts locked on the Staff page; any e-mail change is audited and the old address is told.
- Client address taken from the trusted proxy only (`TRUSTED_PROXY_COUNT`), so forged headers can no longer dodge rate limits or blank the access log.
- Production: demo features off unless `DEMO_MODE=1`; `FIELD_ENCRYPTION_KEY` required, with key rotation (`NEW,OLD` + `manage.py rotate_field_keys`); demo directory and demo seed refused outside demo mode.
- Administrator lock now ends live sessions and blocks Microsoft and AD sign-in; an account disabled here is not re-enabled by a directory sign-in.
- Doctor-portal requests signed with timestamp and single-use nonce (replays refused); malformed payloads return 400.
- API schema requires sign-in; 10-hour absolute session cap enforced; full TRN no longer sent by SMS; application administrators no longer see outbound member messages; CSV exports neutralise spreadsheet formulas; data-subject requests cannot be linked to the wrong member by a junk search.
- **Two-person rule for roles**: roles on local accounts change only by an application administrator's request approved by a manager who is neither the requester nor the person concerned (on the *Staff* record); directory accounts take roles from AD/Entra groups. In the back office roles, group permissions and directory group mappings are read-only except for a superuser.
- Security parameters (retention periods, alert and lookup thresholds, AD re-check interval, deadlines) have enforced minimums and maximums, can be changed only by application administrators and the DPO, and every change is audited.
- An encrypted value that cannot be opened (missing key) is never overwritten on save; `rotate_field_keys` works on the raw values, all or nothing.
- Directory safety: a failed, ambiguous or empty directory search is treated as "directory unreachable", never as "everyone left"; the hourly sync refuses to disable more than 5% of accounts in one run and raises an alert instead.
- The DPO's restriction reason is no longer shown at the counter.
- Image uploads refused above 30 megapixels before decoding; request bodies over 25 MB refused; Permissions-Policy and no-store caching on signed-in pages; hourly per-user limits (with alert) on TRN screening and council register checks; back-office sign-in goes through the staff sign-in page.

Active Directory:
- Signed-in AD users are re-checked against AD every 15 minutes (parameter `directory-recheck-minutes`); anyone disabled or removed from the mapped groups is signed out at once. Directory sync now hourly. AD outages do not sign people out. *Staff* shows "Disabled in directory".

Data Protection Act 2020:
- **Restriction of processing**: the DPO can restrict a member's record from a request (objection, disputed data); no application for that member can be approved until lifted; banner on the member record.
- New request types: review of an automated decision, stop direct marketing.
- **Breach notices**: draft notice to the Information Commissioner (facts, nature and scale, likely consequences, measures, DPO contact) and letter to the people affected; clock for telling the people affected within the same 72 hours.
- **Annual impact assessment** register: draft pre-filled from the processing register and the safeguards in place, DPO approval, recorded submission to the Commissioner.
- Dashboard shows registration with the Commissioner (number and renewal date, warning 60 days ahead), this year's impact assessment, DPO contact details, restricted members.
- Former staff ID records (ID number, ID picture, photo) erased automatically a year after the account is disabled (`staff-id-retention-days`).
- Privacy notice updated (version 2026-11): sensitive health data with written consent, Nursing Council, human decisions, every right under the Act, DPO and Commissioner. Updated automatically where NHF had not edited it.
- Processing register: nurse validation, staff identity records, directory sign-in added.

## v0.2.2 — 29 October 2026 — doctors' practice locations and photos, nurses, council register connector, staff profiles

- **Doctors**: practice address (address, line 2, town/district, parish) alongside the practice name, shown on the register list and profile and searchable by town. Profile photo.
- **Council register connector**: every new MCJ number is checked against the Medical Council register; a doctor in good standing is confirmed automatically, with no manual confirmation needed. Lapsed, suspended, removed or unknown numbers, or a register that cannot be reached, still go to the confirmation queue. Nothing is rejected automatically. Confirmed doctors and nurses are re-checked every night (every 30 days each, adjustable) and anyone the register no longer shows in good standing is flagged on their profile, on the register list and on applications they certify, and council confirmers are notified. *Check register now* button on every profile.
- Two connection modes per council: **local copy** loaded from the register extract the council supplies (*Council register import*: CSV with preview), or the council's **HTTPS verification service** once one is agreed (`MCJ_REGISTER_MODE=https`, `MCJ_REGISTER_URL`, API key). Every check and import is in the Integration Hub log.
- **Nurses register** (Nursing Council of Jamaica): NCJ number, category (registered nurse, midwife, nurse practitioner, enrolled assistant nurse, public health nurse, nurse anaesthetist), workplace and address, photo, register status; *Add a nurse* checks the NCJ register at once; NCJ confirmations sit beside MCJ ones in *Council confirmations*.
- **Staff profiles** (*Staff* under Registry Core): photo, job title, phone, ID type, ID number (encrypted; shown to application administrators and managers, last four characters to auditors), ID expiry and ID picture (each view audited, never cached). Staff can set their own photo from *My account*; it shows in the top bar.
- **Suspend an account**: with a reason and optional end date. Sign-in is refused (local, Active Directory and Microsoft) and every open session ends at once; managers are notified; *Reinstate* lifts it. You cannot suspend yourself or the last application administrator.
- Images are checked, turned upright, resized and re-encoded on upload (removing GPS and camera data and anything hidden in the file), then stored encrypted in the database so they survive redeploys and are in the database backup.
- The *MCJ confirmer* role is now *Council confirmer (MCJ / NCJ)*.

## v0.2.1 — 29 October 2026 — two-step sign-in for all staff, Active Directory, Entra ID

- **Two-step sign-in is now compulsory for every staff account** (Data Protection Act safeguard). Enrolment issues ten single-use backup codes, shown once; *My account* shows how many are left and generates new ones. Using a backup code warns how many remain.
- **Lost phone**: an application administrator can reset another user's two-step sign-in from *User activity* (never their own). Their authenticator and codes are removed, sessions ended, and the reset is audited and raised as a security alert. Repeated wrong codes also raise an alert. The *Security* dashboard shows two-step coverage across all staff.
- **Active Directory connector** (LDAPS): staff sign in with their NHF network username and password. Accounts are created on first sign-in; roles and centre come from AD group mappings (edited in the back office) and are refreshed at every sign-in and nightly. Disabled, removed or unmapped AD accounts are refused and disabled here. Local administrator accounts keep working if the directory is down. A built-in demonstration directory (`LDAP_SERVER_URI=mock://demo`) shows the whole flow without NHF's servers.
- **Microsoft Entra ID single sign-on** (optional): a *Sign in with Microsoft* button. If Microsoft already performed MFA, the system does not ask again.
- New *Directory sign-in* page (application administrator, manager, auditor): configuration without secrets, connection test, group mappings, directory accounts.
- `MFA_DEMO_PRIVILEGED_ONLY=1` lets counter roles skip two-step sign-in **in demo mode only**.

## v0.2.0 — 29 October 2026 — NIS, user tracking, security, Data Protection Act

- **NIS number** on members, applications and change forms; accepted format is a back-office parameter (default one letter + six digits, or nine digits); duplicates blocked; searchable in tracking search; in the API and the access-request export; editable on the profile without an application.
- **User tracking**: every page, search, download and API call by a signed-in user is logged with the record touched, status, time taken and address. *User activity* screen per user and date range with CSV export (both audited). Sessions recorded with device and address; users can sign out their other sessions; administrators can sign a user out everywhere.
- **Security**: self-service password reset by e-mail (throttled, no account enumeration); password expiry (90 days) and history (last 5); letters-plus-number rule; MFA now also required before reaching *My account*, *Temporary roles* and password change; security alerts for repeated failed sign-ins (per username and per address), bulk record viewing and failed TRN checks, notified to administrators and managers; *Security* dashboard with alerts, locked accounts (unlock), active sessions, two-step coverage and password age. Lockout is now per username so one mistyping agent cannot lock a whole centre's shared PC. `docs/security.md` maps the controls to OWASP ASVS for NHF's penetration test.
- **Data Protection Act 2020**: consent to the privacy notice recorded on every application (required before approval) and on the member; data-subject requests with reference, due date, identity check and JSON copy of the member's data (release logged); breach register with the 72-hour reporting clock; processing register (six activities seeded); daily retention sweep with preview (anonymises old rejected applications, purges old access-log rows and notifications); new *Data Protection Officer* role; `docs/data-protection.md`.
- Fixed: contact-detail edits on the member profile were not being saved.

## v0.1.3 — 29 October 2026

- Dark mode for every signed-in screen, switched with the ☾/☀ Theme button in the top bar. The choice is remembered per browser; a first visit follows the computer's light/dark setting. Applied before the page draws, so there is no white flash.

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
