# Demonstration script — v0.1.0

Built from the use cases NHF names (TRN validation, data entry, interaction logging) and the design plan's section 15.
All people, TRNs and doctors are synthetic. Reset with `DEMO_DATA=reseed` on the next deploy, or
`python manage.py seed_demo_data --force` locally.

## Named TRNs (synthetic TRN register)

| TRN | Person (Tax Office record) | Shows |
|---|---|---|
| 100200301 | Marcia Angela Campbell, F, 14 Mar 1979 | Clean match; approval issues member number, card queued, NHF Individual Benefit |
| 100200302 | Tyrese Brown, M, 2 Jul 2014 | Under 18 — guardian required (BR10004) |
| 100200303 | Winston Delroy Grant, M, 20 Nov 1958 | 60+ — JADEP assigned automatically (BR10005) |
| 100200304 | Shanique Ann-Marie Williams, F, 9 May 1990 | Key the form as **Shaniqua** — mismatch table, terminate or re-check (TV10003–TV10005) |
| 100200305 | Paulette Reid, F, 1 Sep 1972 | Tick Benign Prostatic Hyperplasia — blocked as clinically inconsistent (BR10006) |
| 100200306 | Kerry-Ann Thompson-Clarke (member record says Thompson) | Change form → refresh from TRN service → name change, card v2 (BR10003, BR10007) |
| 100200307 | Andre Michael Lewis — existing member | Contact edit without an application (MR10006); interaction logging |
| any other 9 digits, e.g. 100999999 | not in the register | TRN not found — text the applicant, request SRN, or reject (TV10006) |

Doctors: MCJ numbers `10001`, `10008`, `10015` … are in the register. `99901` is the unknown doctor on one online application.

## Run order (about 25 minutes)

1. **Sign-in and roles** — sign in as `mgr.morgan`: enrol the authenticator (QR code), then the manager view. Open
   *Temporary roles* and grant `cc.walker` Supervisor for 8 hours. Sign out.
2. **TRN validation** — as `cc.walker`, *New application*: TRN 100200301, Marcia / Campbell / 14 Mar 1979. Identity
   fills and locks. Start another with 100200304 keyed as *Shaniqua* — show the difference table, then *Terminate*.
   Start one with 100999999 — show *Text the applicant*. Open *TRN / SRN screening* and screen 100200303 without a form.
3. **Data entry with rules** — 100200302: tick Asthma, MCJ 10008, save — guardian check is red; add the guardian,
   save — green. 100200305: tick BPH — blocked. 100200303: Diabetes + Glaucoma — "JADEP will be assigned"; approve —
   member number issued, card queued, enrolled in NHF and JADEP. Show that the name fields cannot be edited.
4. **Interaction logging** — every step above is already in the log on the right. Add a note to an entry. Open member
   100200307 (search the TRN), log a phone call, change the mobile number directly.
5. **Online intake** — *Online Intake*: portal submissions tagged Online, change-form badge, the MCJ-check flag on the
   unknown doctor. Open one; sign in as `cc.brown` in a second browser — "Tanya Walker is working on this record".
   *Simulate portal: new* to show a live arrival.
6. **SRN** — *New application* → *No TRN?* panel: request an SRN. As `mgr.morgan`: *SRN approvals* → duplicate check →
   approve; a 9-prefixed SRN is issued and the application continues.
7. **MCJ confirmation** — as `mgr.morgan`: *MCJ confirmations* → 99901 → *Not confirmed*; the online application is
   rejected with "Doctor not confirmed by the Medical Council".
8. **Configuration** — as `backoffice.lee`: `/backoffice/` → Medical conditions → add a condition; it appears on the
   counter form at once with no code change.
9. **Audit and privacy** — as `auditor.shaw`: open a member — conditions hidden; *Audit trail* shows the session.

Card printing, verification by swipe and dispatch with signature (design plan steps 6) arrive in sprint A2;
dashboards and saved reports (step 8) in A3.

## v0.2 additions

10. **NIS number** — search `B204517` in the top bar: it opens member 100200307 (Andre Lewis). Edit his NIS on the profile; try another member's NIS on an application — blocked as a duplicate.
11. **Consent** — any open application: the red *JDPA* check stays until the consent box under the privacy notice is ticked and saved.
12. **User activity** — as `auditor.shaw`: *User activity* → `cc.walker` → every page and event of the session, then *Export CSV*.
13. **Security** — sign in five times with a wrong password for `cc.brown`: a high alert appears on *Security* and in managers' inboxes; the account shows under *Locked accounts* with *Unlock* (application administrator).
14. **Data protection** — as `dpo.grant`: *Privacy dashboard* → the open access request from Andre Lewis → *Download copy of the member's data*; the release appears on his interaction log. *Breach register* shows the hours left to report to the Information Commissioner.

## v0.2.1 additions

15. **Two-step for everyone** — sign in as `cc.walker`: scan the QR code, enter the code, and the ten backup codes appear once. Sign out and back in: the code is asked for. Enter one backup code instead: it works once and you are told how many are left.
16. **Lost phone** — as `ictadmin.james`: *User activity* → `cc.walker` → *Reset two-step sign-in* with a reason. `cc.walker` is signed out and enrols again; *Security* shows the alert. Try it on your own account: refused.
17. **Active Directory** (`LDAP_ENABLED=1`, `LDAP_SERVER_URI=mock://demo`) — sign in as `ad.campbell` with the demo password: an account is created as Customer Care at Half-Way-Tree from her AD groups. `ad.nogroup` is told they are not in a group that gives access; `ad.disabled` is told the account is disabled.
18. **Directory page** — as `ictadmin.james`: *Directory sign-in* → look up `ad.henry` → *Test connection* shows the bind, his groups and that he is enabled; *Edit group mappings* changes which group gives which role.
