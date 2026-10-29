# Requirement coverage — v0.1.0

Against NHF's Functional_Requirements.xlsx and Technical_Requirements.xlsx. **Built** = working in this release;
**Mock** = working end to end against a mock adapter (real endpoint is configuration in Phase B);
**A2 / A3** = next Phase A sprints; **B** = Phase B on NHF's infrastructure.

## Functional

| Group | Rows | Status | Where |
|---|---|---|---|
| Member Registration | MR10001–03, MR10005–16 | Built | `members` — context, channels, online auto-tag, tracking and member numbers, change forms, contact edits, rejection with reasons, conditions with severity, search |
| | MR10004 | Mock | PHI upsert after approval (`IntegrationRun` system `phi`); card flagged for printing |
| Eligibility and Business Rules | BR10001–11 | Built | DB trigger locks name/DOB/gender; rules engine; card version on reprint; reprint only for replacement or name/DOB change; programmes, benefits, conditions in `/backoffice/` |
| TRN Validation | TV10001–08 | Mock | Mock adapter over a synthetic register; SOAP client (`SoapTrnAdapter`) ready for the ICTA WSDL; circuit breaker; fresh call every time |
| Special Registration Number | SR10001–06 | Built | Request, manager approval (not the requester), 9-prefix random, collision-free, duplicate check, stored in the TRN field with annotation, screening |
| Doctor Validation | DV10001–05 | Built | Register lookup, unknown → MCJ confirmation queue, non-confirmation rejects, Customer Care edits profiles |
| Online Registration | OR10001–02, OR10004–10 | Built | Signed `/api/intake/portal/`, TRN validated on arrival, online queue, new/change, change flag, referring doctor, worked-by indicator |
| | OR10003 | Built / Mock | E-mail to Customer Care through the mail backend; SMS recorded as preview until the gateway is connected |
| Card Printing | CP10003, CP10006, CP10007 | Built | Print queue of flagged cards, card table with ISO 7811 tracks, cleaned print names |
| | CP10001, CP10002, CP10004, CP10005 | A2 | PHI reconciliation before print, encoding register, spoil override, daily reset |
| Card Verification | CV10001–04 | A2 | Swipe (keyboard wedge) and reconciliation |
| Card Dispatch | CD10001–10 | A2 | Serial, recipient, signature pad, entry-to-dispatch time, serial report |
| Interaction Logging | IL10001–02 | Built | Append-only log (DB-enforced) with notes |
| Application Tracking | AT10001 | Built | TRN, tracking number, member number, programme |
| Form Scanning | FS10001–06 | A3 | Scan/upload, OCR pre-fill, batch intake, retention |
| Reporting | RP10001–03 | A3 | Dashboards, saved reports, export (home counters only now) |

## Technical

| Group | Rows | Status | Notes |
|---|---|---|---|
| User Management | UM10001, 02, 04, 07, 08, 09, 10, 11 | Built | Sign-in, accounts via back office, TOTP MFA by role, temporary roles, Argon2, audit, TRN identity check, axes lockout + admin lock |
| | UM10003 | A3 | Self-service account recovery |
| | UM10005, UM10006 | B | AD over LDAPS and OIDC/Entra (packages in `requirements-integrations.txt`) |
| Data Management | DM10001, DM10002, DM10004, DM10005 | Built | Fernet field encryption for TRN payloads and notes, TLS at the proxy; role-based access + audit; separate settings per environment |
| | DM10003 | B | pgBackRest on NHF's servers |
| Integration | IN10001, IN10003, IN10006 | Built | REST + OpenAPI at `/api/docs/`, run log, portal endpoint |
| | IN10002, IN10004, IN10007 | Mock | SOAP TRN client, PHI, SMS behind adapters |
| | IN10005 | A2 | Signature pad |
| Audit | AL10001, AL10002 | Built | Append-only audit (DB-enforced) with user, IP and request id; error logging to the container log |
| Notifications | NT10001, NT10004 | Built | In-app inbox, e-mail, SMS preview, links to records |
| | NT10002, NT10003 | A3 | Recurring reminders, escalation of overdue items |
| Reporting and Analytics | RA10001–03 | A3 | |
| Compliance and Security | CS10002, CS10005 | Built | Conditions masked outside clinical roles; CSP with nonces, CSRF, secure cookies, lockout |
| | CS10001, CS10003, CS10004 | A3 / B | JDPA artefacts, threat alerts, VAPT by Brian |
| Performance | PF10002 | Built | TRN calls off the request path with polling; indexed lookups |
| | PF10001 | A2 | Counter-to-dispatch timing |
| Availability, Scalability, Portability | PT10001–02, SC10001 | Built | One container image for web/worker/beat; stateless web tier |
| | AV10001–02, SC10002 | B | Two app nodes, DB replica, downtime procedure |
| Usability | US10001–03 | Built | Keyboard-first counter screen, configuration without code, queues and status badges |
| Maintainability | MU10001–03 | Built | Parameters in the back office, OpenAPI, separate environments |
