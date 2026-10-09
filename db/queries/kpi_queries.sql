-- KPI queries (MySQL 8). Each block starts with a "-- name:" marker so scripts and the API can load it by name.
-- Rules: every query reads from v_active_encounters / v_readmission_base (never from encounters directly);
-- every readmission rate = 30-day readmissions among ELIGIBLE encounters / ELIGIBLE encounters;
-- patient counts use COUNT(DISTINCT patient_nbr); age groups are ordered by age_order, never alphabetically.
-- Counts and average length of stay use ALL active encounters; only the rate uses the eligible denominator.

-- name: headline
-- Business question: how big is the activity, and what share of eligible encounters is readmitted within 30 days?
-- Denominator: eligible encounters for both rates; all active encounters for the counts and averages.
SELECT
    COUNT(*) AS total_encounters,
    COUNT(DISTINCT patient_nbr) AS unique_patients,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    ROUND(AVG(1.000000 * num_medications), 6) AS avg_num_medications,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND any_readmission = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS any_readmission_rate
FROM v_active_encounters;

-- name: by_age_group
-- Business question: how do volume, length of stay and 30-day readmission differ by age group?
-- Denominator: eligible encounters in the age group. Ordered by age_order (0-10 first, 90-100 last).
SELECT
    age_order, age_group,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY age_order, age_group
ORDER BY age_order;

-- name: by_admission_type
-- Business question: which admission types have longer stays or higher 30-day readmission?
-- Denominator: eligible encounters of that admission type.
SELECT
    admission_type_id, admission_type,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY admission_type_id, admission_type
ORDER BY encounters DESC;

-- name: by_admission_source
-- Business question: do patients admitted from different sources readmit at different rates?
-- Denominator: eligible encounters from that admission source.
SELECT
    admission_source_id, admission_source,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY admission_source_id, admission_source
ORDER BY encounters DESC;

-- name: by_discharge_disposition
-- Business question: which discharge destinations are associated with the highest 30-day readmission?
-- Denominator: eligible encounters with that disposition (expired/hospice rows have 0 eligible encounters).
SELECT
    discharge_disposition_id, discharge_disposition,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY discharge_disposition_id, discharge_disposition
ORDER BY encounters DESC;

-- name: by_medical_specialty
-- Business question: which medical specialties are associated with higher 30-day readmission? (49% unknown)
-- Denominator: eligible encounters of that specialty; missing specialty is reported as Unknown.
SELECT
    COALESCE(medical_specialty, 'Unknown') AS medical_specialty,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY COALESCE(medical_specialty, 'Unknown')
ORDER BY encounters DESC;

-- name: monthly_trend
-- Business question: how do encounters, length of stay and the 30-day rate move month by month? (SIMULATED dates)
-- Denominator: eligible encounters admitted in the month.
SELECT
    DATE_FORMAT(admission_date, '%Y-%m') AS month,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY DATE_FORMAT(admission_date, '%Y-%m')
ORDER BY month;

-- name: yearly_trend
-- Business question: how do encounters, length of stay and the 30-day rate move year by year? (SIMULATED dates)
-- Denominator: eligible encounters admitted in the year.
SELECT
    YEAR(admission_date) AS year,
    COUNT(*) AS encounters,
    ROUND(AVG(1.000000 * time_in_hospital), 6) AS avg_length_of_stay,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY YEAR(admission_date)
ORDER BY year;

-- name: monthly_moving_average
-- Business question: what is the smoothed (3-month moving average) 30-day readmission rate? (SIMULATED dates)
-- Denominator: eligible encounters per month; the average is the mean of the current and two previous monthly rates.
WITH monthly AS (
    SELECT
        DATE_FORMAT(admission_date, '%Y-%m') AS month,
        1.000000 * SUM(CASE WHEN readmitted_30d = 1 THEN 1 ELSE 0 END) / COUNT(*) AS rate
    FROM v_readmission_base
    GROUP BY DATE_FORMAT(admission_date, '%Y-%m')
)
SELECT
    month,
    ROUND(rate, 6) AS readmission_rate_30d,
    ROUND(AVG(rate) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 6) AS rate_3m_moving_avg
FROM monthly
ORDER BY month;

-- name: top_drugs
-- Business question: which 10 drugs are prescribed most often, and how do their encounters readmit within 30 days?
-- Denominator: eligible encounters in which the drug was prescribed (Steady, Up or Down).
SELECT
    m.drug_name,
    COUNT(*) AS encounters,
    SUM(v.is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN v.is_readmission_eligible = 1 AND v.readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN v.is_readmission_eligible = 1 AND v.readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(v.is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters v
JOIN encounter_medications em ON em.encounter_id = v.encounter_id
JOIN medications m ON m.medication_id = em.medication_id
GROUP BY m.drug_name
ORDER BY encounters DESC, m.drug_name
LIMIT 10;

-- name: insulin_status
-- Business question: is insulin dosage status (No / Steady / Up / Down) associated with 30-day readmission?
-- Denominator: eligible encounters with that insulin status (No = no insulin row stored, i.e. not prescribed).
SELECT
    COALESCE(em.dosage_status, 'No') AS insulin_status,
    COUNT(*) AS encounters,
    SUM(v.is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN v.is_readmission_eligible = 1 AND v.readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN v.is_readmission_eligible = 1 AND v.readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(v.is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters v
LEFT JOIN medications m ON m.drug_name = 'insulin'
LEFT JOIN encounter_medications em ON em.encounter_id = v.encounter_id AND em.medication_id = m.medication_id
GROUP BY COALESCE(em.dosage_status, 'No')
ORDER BY FIELD(insulin_status, 'No', 'Steady', 'Up', 'Down');

-- name: a1c_result
-- Business question: is the A1C test result (None = not tested) associated with 30-day readmission?
-- Denominator: eligible encounters with that A1C result.
SELECT
    a1c_result,
    COUNT(*) AS encounters,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY a1c_result
ORDER BY FIELD(a1c_result, 'None', 'Norm', '>7', '>8');

-- name: prior_inpatient
-- Business question: do patients with more prior inpatient visits readmit more often?
-- Denominator: eligible encounters in the bucket (0, 1, 2, 3+ prior inpatient visits).
SELECT
    CASE WHEN number_inpatient >= 3 THEN '3+' ELSE CAST(number_inpatient AS CHAR) END AS prior_inpatient_visits,
    COUNT(*) AS encounters,
    SUM(is_readmission_eligible) AS eligible_encounters,
    SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END) AS readmitted_30d_count,
    ROUND(1.000000 * SUM(CASE WHEN is_readmission_eligible = 1 AND readmitted_30d = 1 THEN 1 ELSE 0 END)
          / NULLIF(SUM(is_readmission_eligible), 0), 6) AS readmission_rate_30d
FROM v_active_encounters
GROUP BY CASE WHEN number_inpatient >= 3 THEN '3+' ELSE CAST(number_inpatient AS CHAR) END
ORDER BY prior_inpatient_visits;

-- name: frequent_patients
-- Business question: how many patients have 3 or more encounters, and how much activity do they account for?
-- Counts only, no identifiers (data minimisation). Patients counted with COUNT(DISTINCT patient_nbr).
SELECT
    COUNT(DISTINCT patient_nbr) AS patients_with_3plus_encounters,
    COALESCE(SUM(encounter_count), 0) AS encounters_of_those_patients
FROM (
    SELECT patient_nbr, COUNT(*) AS encounter_count
    FROM v_active_encounters
    GROUP BY patient_nbr
    HAVING COUNT(*) >= 3
) AS frequent;

