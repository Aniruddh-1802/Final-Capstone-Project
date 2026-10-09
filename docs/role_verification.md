# Role verification (UI versus direct API)

Run by `frontend/e2e/run.mjs` on 2026-10-08 with headless Chrome against the real API and database. For every role and action the script recorded what the UI shows and what the API answers when the same call is made directly with that role's token (`fetch` with the Authorization header from the session). The UI only hides things; the API status is the real enforcement.

| Role | Action | UI behaviour | Direct API status | Agree |
|---|---|---|---|---|
| administrator | Open Dashboard | opens (Dashboard) | 200 | yes |
| administrator | Open Patients | opens (Patients) | 200 | yes |
| administrator | Open Encounters | opens (Encounters) | 200 | yes |
| administrator | Open Reports | opens (Reports) | 200 | yes |
| administrator | Open Pipeline Runs | opens (Pipeline runs) | 200 | yes |
| administrator | Open Data Quality | opens (Data quality) | 200 | yes |
| administrator | Open Audit Log | opens (Audit log) | 200 | yes |
| administrator | Open Users | opens (Users) | 200 | yes |
| administrator | Create encounter | “New encounter” button shown | 201 | yes |
| administrator | Delete encounter | “Delete” button shown | 204 | yes |
| administrator | Encounter-level export | option offered | 200 | yes |
| administrator | Aggregated export | option offered | 200 | yes |
| administrator | Report history table | table shown | 200 | yes |
| clinical_ops | Open Dashboard | opens (Dashboard) | 200 | yes |
| clinical_ops | Open Patients | opens (Patients) | 200 | yes |
| clinical_ops | Open Encounters | opens (Encounters) | 200 | yes |
| clinical_ops | Open Reports | opens (Reports) | 200 | yes |
| clinical_ops | Open Pipeline Runs | opens (Pipeline runs) | 200 | yes |
| clinical_ops | Open Data Quality | opens (Data quality) | 200 | yes |
| clinical_ops | Open Audit Log | Not permitted page | 403 | yes |
| clinical_ops | Open Users | Not permitted page | 403 | yes |
| clinical_ops | Create encounter | “New encounter” button shown | 201 | yes |
| clinical_ops | Delete encounter | “Delete” button hidden | 403 | yes |
| clinical_ops | Encounter-level export | option offered | 200 | yes |
| clinical_ops | Aggregated export | option offered | 200 | yes |
| clinical_ops | Report history table | table shown | 200 | yes |
| analyst | Open Dashboard | opens (Dashboard) | 200 | yes |
| analyst | Open Patients | Not permitted page | 403 | yes |
| analyst | Open Encounters | opens (Encounters) | 200 | yes |
| analyst | Open Reports | opens (Reports) | 200 | yes |
| analyst | Open Pipeline Runs | Not permitted page | 403 | yes |
| analyst | Open Data Quality | Not permitted page | 403 | yes |
| analyst | Open Audit Log | Not permitted page | 403 | yes |
| analyst | Open Users | Not permitted page | 403 | yes |
| analyst | Create encounter | button hidden | 403 | yes |
| analyst | Delete encounter | no detail actions (read-only) | 403 | yes |
| analyst | Encounter-level export | option hidden | 403 | yes |
| analyst | Aggregated export | option offered | 200 | yes |
| analyst | Report history table | table hidden | 403 | yes |

API status meaning: 200/201/204 = allowed, 403 = forbidden by role (401 would mean no or invalid token).

## Other checks

| Check | Result | Detail |
|---|---|---|
| administrator: navigation shows exactly the allowed pages | PASS | Dashboard, Patients, Encounters, Reports, Pipeline Runs, Data Quality, Audit Log, Users |
| administrator: top bar shows username and role badge | PASS |  |
| clinical_ops: navigation shows exactly the allowed pages | PASS | Dashboard, Patients, Encounters, Reports, Pipeline Runs, Data Quality |
| clinical_ops: top bar shows username and role badge | PASS |  |
| analyst: navigation shows exactly the allowed pages | PASS | Dashboard, Encounters, Reports |
| analyst: top bar shows username and role badge | PASS |  |
| token is kept in sessionStorage, not localStorage | PASS |  |
| deleting the token and refreshing lands on the login page | PASS |  |
| a refresh keeps the session | PASS |  |
| every API call (except login) carries the Authorization header | PASS | 291 requests |
| no token appears in any URL | PASS |  |
| an invalid token is rejected and sends the user to login (401 handled centrally) | PASS |  |
| KPI card "Encounters" equals the API value | PASS | 91,566 |
| KPI card 30-day rate equals the API value (formatted) | PASS | 11.43% |
| simulated-dates banner is shown | PASS |  |
| age groups are in clinical order, 0-10 first and 90-100 last | PASS | [0-10) [10-20) [20-30) [30-40) [40-50) [50-60) [60-70) [70-80) [80-90) [90-100) |
| age-group table counts add up to the Encounters card | PASS |  |
| after rapid filter changes the cards show the LAST selection | PASS | 17,014 vs API 17014 |
| invalid length of stay: message appears under the right field | PASS | Enter a whole number from 1 to 14. |
| invalid form is not sent to the API | PASS |  |
| server 422 (unknown patient) is mapped onto the Patient number field | PASS | patient 123 does not exist |
| valid encounter is created and a success toast is shown | PASS |  |
| edit saved and the server derived readmitted_30d = true | PASS |  |
| deleted encounter disappears from the list | PASS |  |
| audit log shows exactly CREATE, UPDATE, DELETE for what was just done | PASS | CREATE, UPDATE, DELETE |
| UPDATE audit row shows only the fields that changed | PASS | readmitted, readmitted_30d, any_readmission |
| pipeline page shows status, counts and reject ratio | PASS |  |
| Excel report downloads through the UI with authentication (blob, no token in URL) | PASS | readmission_summary_20261009_002149.xlsx |
| an oversized encounter export shows the server's helpful 413 message | PASS |  |
| analyst encounter table has no patient column and no create button | PASS | Encounter, Admitted (simulated), Age, Admission type, Days, Meds, Readmitted |
| analyst has no patient-number filter | PASS |  |
| analyst opening /patients sees "Not permitted" | PASS |  |
