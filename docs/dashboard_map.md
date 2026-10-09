# Dashboard map: chart, business question, endpoint

Every number on the dashboard comes from the analytics API; the browser only formats values (counts with thousands separators, rates as percentages) and never computes a rate. All requests use one debounced filter object (300 ms): `date_from`, `date_to`, `age_group`, `admission_type_id`. A new filter aborts the in-flight requests and any late response is ignored (`useApi`), so the page always shows the last selection.

| Element | Business question it answers | Endpoint and parameters |
|---|---|---|
| KPI: Encounters, Unique patients, Average length of stay, 30-day readmission rate, Medications per encounter | How big is the activity and what share of eligible encounters is readmitted within 30 days? | `GET /analytics/summary` + filters |
| Admissions over time (month / year toggle) | How many encounters were admitted per month or year? (simulated dates) | `GET /analytics/admissions-trend?granularity=month|year` |
| 30-day readmission rate over time | Is the 30-day rate changing month to month? (simulated dates) | `GET /analytics/readmissions?group_by=month` |
| Length of stay by admission type | Do some admission types stay longer? | `GET /analytics/length-of-stay?group_by=admission_type` |
| Length of stay distribution | How many encounters last 1 to 14 days? | `GET /analytics/length-of-stay?group_by=overall` (histogram, aggregated by the server) |
| Readmission by age group | Which age groups have a higher 30-day rate? (clinical order from the API) | `GET /analytics/readmissions?group_by=age_group` |
| Readmission by admission source | Does the rate differ by where patients were admitted from? | `GET /analytics/readmissions?group_by=admission_source` |
| Readmission by medical specialty (top 10 by volume) | Which common specialties are associated with a higher rate? | `GET /analytics/readmissions?group_by=specialty` (first 10 rows, ordered by volume by the API) |
| Insulin dosage and readmission | Is insulin dosage status (No / Steady / Up / Down) associated with the 30-day rate? | `GET /analytics/medications` -> `insulin_status` |
| A1C result and readmission | Is the A1C test result associated with the 30-day rate? | `GET /analytics/medications` -> `a1c_result` |
| Prior inpatient visits and readmission | Do patients with more earlier inpatient visits have a higher rate? | `GET /analytics/utilization` |

A chart that answered no question was not built. Every chart card states its question, has a "View as table" toggle with the same numbers, a loading skeleton, an empty state and an error state with Retry.

## Honest labelling
* A banner on the dashboard, the encounter lists, patient encounters and reports pages: "Admission dates in this dataset are simulated".
* The rate card has a tooltip: readmitted within 30 days divided by **eligible** encounters; expired and hospice discharges are excluded from the denominator. A caption under the cards shows eligible versus total encounters.
* Groups with fewer than 11 encounters (`small_n` from the API) are drawn in grey, marked with `*` in the table view and footnoted.
* Wording is "associated with", never "caused by"; a test fails if the page contains causal language.
* Colours: the Okabe-Ito colour-blind-safe palette; layout is responsive from laptop to tablet width.

## Role-to-route table (what the UI shows; the API enforces)
| Route | administrator | clinical_ops | analyst |
|---|---|---|---|
| `/dashboard` | yes | yes | yes |
| `/encounters` | yes (create, edit, delete) | yes (create, edit) | read-only, no patient column or filter |
| `/reports` | all reports + history | all reports + history | aggregated reports only |
| `/patients`, `/patients/:id` | yes | yes (no delete) | Not permitted |
| `/pipeline`, `/data-quality` | yes | yes | Not permitted |
| `/audit`, `/users` | yes | Not permitted | Not permitted |

Role-by-role UI-versus-API results from a real browser run are in `docs/role_verification.md`; screenshots are in `docs/screenshots/`.
