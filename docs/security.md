# Security controls — v0.2.3

For NHF's ICT team and the penetration testers. Mapped to OWASP ASVS 4.0.3 Level 2 chapters and to the tender rows
(UM, DM, AL, CS). Each control names where it lives so it can be checked in code or on screen.

## 1. Authentication (ASVS V2; UM10001–UM10011)

| Control | Where |
|---|---|
| Passwords hashed with Argon2id (PBKDF2 fallback for migration only) | `PASSWORD_HASHERS` in `config/settings/base.py` |
| Minimum 12 characters, common/numeric/similar-to-username rejected, letters plus a number or symbol | `AUTH_PASSWORD_VALIDATORS`, `apps/accounts/validators.py` |
| No reuse of the last N passwords (parameter `password-history-count`, default 5) | `PasswordHistory`, `PasswordHistoryValidator` |
| Expiry after N days (parameter `password-max-age-days`, default 90; 0 turns it off) | `PasswordExpiryMiddleware` |
| Self-service reset by e-mailed single-use link (3-day expiry), max 5 requests per hour per address, response does not reveal whether the e-mail exists | `ThrottledPasswordResetView` |
| TOTP two-step sign-in compulsory for **every** staff account (`MFA_REQUIRED`, default on). Manager, application administrator, database administrator and DPO can never be exempted. `MFA_DEMO_PRIVILEGED_ONLY=1` relaxes it for other roles only while `DEMO_MODE=1`; it is ignored in production | `MFAEnforcementMiddleware`, `mfa_required_for` |
| Ten single-use backup codes issued at enrolment, shown once; used codes are consumed; users regenerate them from *My account* | `issue_backup_codes`, django-otp static devices |
| Lost authenticator: an application administrator resets another user's two-step sign-in (never their own); devices and backup codes deleted, sessions ended, audit entry and a security alert | `security:reset-mfa` |
| Repeated wrong two-step codes (parameter `alert-failed-mfa`, default 5 in 15 minutes) raise a high alert — the password may be known to someone else | `_count_mfa_failure` |
| Before the second factor is verified only sign-in, sign-out, MFA and password-reset pages are reachable | `OPEN_PATHS` in `apps/accounts/middleware.py` |
| Lockout after 5 failures for 15 minutes (per username — shared counter PCs are not locked); administrator unlock on the Security page | django-axes, `security:unlock` |
| Administrator temporary lock of an account | `User.locked_until` |
| Account suspension (reason, optional end date): sign-in refused on every route (password, AD, Entra ID), all sessions ended immediately, any request from a suspended account signs it out; no self-suspension; the last application administrator cannot be suspended; audited and notified to managers | `apps/accounts/staff.py`, `MFAEnforcementMiddleware` |
| Active Directory sign-in over LDAPS (UM10005): service-account bind, user found by sAMAccountName, password checked by binding as the user (never stored locally), disabled AD accounts refused, nested groups via the AD in-chain rule, LDAP filters escaped, certificate required, plain `ldap://` refused unless `LDAP_ALLOW_PLAIN=1` (lab only) | `apps/directory/ldap.py`, `ActiveDirectoryBackend` |
| Roles and centre come from AD group mappings, refreshed at every sign-in; nobody in a mapped group → no account; directory accounts have no local password; a local account is never taken over by a matching directory name; nightly sync disables accounts removed, disabled or unmapped in AD and ends their sessions | `apps/directory/provisioning.py`, `sync_ad_users` |
| Local break-glass administrator still signs in if the directory is down | `ActiveDirectoryBackend` skips local accounts with a password |
| Microsoft Entra ID single sign-on (UM10006): OpenID Connect authorisation code with PKCE, state and nonce; ID token signature checked against Entra's published keys, plus issuer, audience and expiry. When Entra reports MFA (`amr` contains `mfa`) our prompt is skipped for that session; otherwise our TOTP is still required | `apps/directory/oidc.py` |

## 2. Sessions (ASVS V3)

| Control | Where |
|---|---|
| HttpOnly, SameSite=Lax, Secure cookies in production; HSTS one year | `config/settings/prod.py` |
| Idle timeout 30 minutes, absolute 10 hours | `SESSION_IDLE_MINUTES`, `SESSION_COOKIE_AGE` |
| Every sign-in recorded with device and address; users can end their other sessions; administrators can sign a user out everywhere | `UserSession`, *My account*, *User activity* |
| Session key rotated at sign-in | Django `login()` |

## 3. Access control (ASVS V4; UM10007; TOR §4)

| Control | Where |
|---|---|
| Role catalogue: global, process-specific, temporary roles with expiry | `apps/accounts/roles.py`, *Temporary roles* |
| Application administrator separated from database administrator; neither sees member records | `ROLES`, `role_required` on every view |
| Medical conditions shown only to roles that process eligibility | `CLINICAL_VIEW_ROLES` |
| Centre scoping: counter roles list and work only their centre's applications and cards (read-only elsewhere unless assigned); island-wide roles see all; member records searchable island-wide with every view logged | `apps/accounts/scoping.py` |
| Approver of an SRN cannot be its requester | `approve_srn` |
| Server-side checks on every POST; no client-side-only rules | views |

## 4. Input, output and browser protections (ASVS V5, V14)

| Control | Where |
|---|---|
| Django forms validation, ORM parameterised queries, auto-escaping templates | throughout |
| Content-Security-Policy with per-request nonces, no inline script without nonce, frame-ancestors none | `CONTENT_SECURITY_POLICY` |
| CSRF on every form and HTMX request | `CsrfViewMiddleware`, `hx-headers` |
| X-Content-Type-Options, Referrer-Policy, COOP, X-Frame-Options DENY | settings |
| Doctor-portal endpoint authenticated by HMAC-SHA256 over the body, rate-limited | `apps/api/views.py` |
| Upload virus scanning | with document scanning (sprint A3) |

## 5. Data protection at rest and in transit (ASVS V6, V8, V9; DM10001)

| Control | Where |
|---|---|
| TRN-service payloads and condition notes encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under a separate key | `apps/core/crypto.py`, `FIELD_ENCRYPTION_KEY` |
| Name, date of birth, gender and TRN of a member changeable only through the TRN service, enforced by a PostgreSQL trigger | `members/migrations/0002` |
| TLS 1.2+ terminated at nginx / the platform proxy | deployment |

## 6. Logging and monitoring (ASVS V7; AL10001–AL10002; CS10003)

| Control | Where |
|---|---|
| Business audit trail (who, what, when, record, address, request id); database refuses UPDATE/DELETE | `AuditEvent`, `core/migrations/0002` |
| Every page, search, download and API call by a signed-in user, with the record touched and response time | `AccessLog` |
| User activity timeline and CSV export; viewing or exporting it is itself audited | *User activity* |
| Alerts: repeated failed sign-ins, unusual number of member records opened, unusual number of failed TRN checks, sessions ended by an administrator; administrators and managers notified | `apps/security/services.py`, *Security* |
| Interaction log append-only in the database | `interactions/migrations/0002` |

## 7. Supply chain and build (ASVS V10, V14)

| Control | Where |
|---|---|
| ruff (incl. flake8-bandit rules), bandit, pip-audit on every push; deploy checks | `.github/workflows/ci.yml` |
| Container runs as a non-root user; health check | `Dockerfile` |
| Secrets only from environment variables | `.env.example` |

## 8. For the penetration test

Test accounts are the demo users in the README (synthetic data only). Points worth testing: role bypass on POST
endpoints, the identity-field trigger (`UPDATE members_member SET last_name=…` must fail), portal HMAC, CSP, lockout,
session revocation, password-reset token reuse, and access to `/privacy/` and `/security/` by non-privileged roles.

## Photos and identity documents (v0.2.2)

| Control | Where |
|---|---|
| Uploads limited to 8 MB, opened and verified with Pillow, only JPEG/PNG/WebP accepted, 50-megapixel decompression-bomb limit | `apps/core/images.py` |
| Every image re-encoded as a new JPEG: EXIF (GPS position, camera serial) and anything appended to the file removed; resized (photos 512 px, ID pictures 1,600 px) | `images.store` |
| Stored encrypted (Fernet, field key) in PostgreSQL, not in a web-served folder; served only through `/images/<id>/` after a role check | `StoredImage`, `core:image` |
| Staff ID pictures: application administrators and managers only, `Cache-Control: no-store`, every view audited; ID numbers encrypted, masked to the last four characters for auditors | `VIEW_ROLES`, `User.id_number` |
| Council register calls: HTTPS only, API key from environment, timeout, circuit breaker, logged in the Integration Hub | `apps/doctors/registers.py` |

## v0.2.3 review

An independent code review in October 2026 found 18 issues; a second pass confirmed the fixes and found 4 more in the
new code, also fixed (one critical: enrolling a new authenticator with only a
password). All are fixed and each has a regression test in `tests/test_v023_security_fixes.py`. Dependency scans
(`pip-audit`, `npm audit`), `bandit` and `manage.py check --deploy` are clean.

| Control | Where |
|---|---|
| Existing second factor required before enrolling or replacing an authenticator | `mfa_setup` |
| Temporary-role grant matrix; no self-grants; privileged roles never granted temporarily | `GRANTABLE` in `apps/accounts/views.py` |
| Back office: no self-edit; superuser, permissions, privileged e-mail/password only by a superuser; changes audited; sign-in through the staff page | `apps/accounts/admin.py`, `config/urls.py` |
| Client address from the trusted proxy entry only | `apps/core/net.py`, `TRUSTED_PROXY_COUNT` |
| Demo features off in production unless `DEMO_MODE=1`; field key required; key rotation | `config/settings/prod.py`, `apps/core/crypto.py`, `rotate_field_keys` |
| Lock and suspension end live sessions on every sign-in route | `MFAEnforcementMiddleware`, `oidc.py`, `backends.py` |
| AD account state re-checked every 15 minutes during a session; hourly sync | `apps/directory/middleware.py` |
| Portal requests: HMAC over timestamp + nonce + body, 5-minute window, nonce single use | `apps/intake/services.py` |
| Two-person rule for roles (request by administrator, approval by a different manager); roles, group permissions and group mappings read-only in the back office except for a superuser | `apps/accounts/staff.py`, `admin.py`, `bootstrap_roles.py` |
| Security parameters bounded in code and editable only by administrators / DPO, with audit | `PARAMETER_LIMITS` in `apps/core/models.py`, `apps/core/admin.py` |
| Undecryptable values preserved on save; all-or-nothing key rotation | `apps/core/crypto.py`, `rotate_field_keys` |
| Directory mis-configuration cannot mass-disable accounts (empty or failed search = unreachable; 5% hold) | `apps/directory/ldap.py`, `services.py` |
| API schema behind sign-in; absolute 10-hour session; CSV formula neutralising; per-user lookup limits; 25 MB request cap; Permissions-Policy; no-store on signed-in pages | settings, `apps/core/*` |

