# Security controls — v0.2.0

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
| TOTP two-step sign-in, compulsory for manager, application administrator, database administrator and DPO roles (or all staff with `MFA_REQUIRED=1`) | `MFAEnforcementMiddleware` |
| Before the second factor is verified only sign-in, sign-out, MFA and password-reset pages are reachable | `OPEN_PATHS` in `apps/accounts/middleware.py` |
| Lockout after 5 failures for 15 minutes (per username — shared counter PCs are not locked); administrator unlock on the Security page | django-axes, `security:unlock` |
| Administrator temporary lock of an account | `User.locked_until` |
| AD (LDAPS) and Entra ID (OIDC) sign-in | Phase B, `requirements-integrations.txt` |

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
