# Data Protection Act 2020 — how the system supports NHF's obligations

NHF is the data controller; the contractor is the processor (NHF's Data Processing Agreement). The system gives the
Fund's Data Protection Officer the records and tools below. Periods and texts are parameters in the back office.

| Obligation | What the system does | Screen |
|---|---|---|
| Lawful processing, explicit consent for health data | Every application records consent to the privacy notice (with time and notice version) before it can be approved; doctor-portal submissions carry the consent given to the doctor; consent stays on the member record | Counter screen, member profile |
| Transparency | Privacy notice text shown on the form; processing register lists purposes, recipients and retention | *Processing register* |
| Data minimisation and need-to-know | Medical conditions hidden from roles that do not process eligibility; auditors see masked data | All member screens |
| Accuracy and correction | Corrections through change forms; name and date of birth only from the TRN service | Change form |
| Rights of the data subject (access, correction, objection, erasure) | Requests logged with a reference and due date (parameter `dsr-days`, default 30); identity check before release; JSON copy of everything held about the member; every release logged on the request, in the audit trail and on the member | *Requests from members* |
| Storage limitation | Daily retention sweep: rejected/terminated applications anonymised after `retention-rejected-days` (default 730); access log purged after `access-log-retention-days` (365); notifications after 12 months; preview before running; approved members never removed by the sweep | *Privacy dashboard* |
| Security | See `docs/security.md` | *Security* |
| Breach notification | Breach register with severity, people affected, containment and actions; deadline to report to the Information Commissioner (`breach-report-hours`, default 72) counted from discovery, overdue flagged; DPO and managers notified | *Breach register* |
| Accountability | Record of processing activities maintained by the DPO; audit of every access; user activity reports | *Processing register*, *User activity* |
| Cross-border transfer | None: production runs on NHF's own servers | Processing register |

Open point for NHF's DPO: the interaction log and audit trail are append-only by design (tender rows IL10002, AL10001),
so personal details written into their summaries are not removed by the retention sweep. Agree the retention period for
these logs at inception; the sweep can be extended to archive them off-line after that period.
