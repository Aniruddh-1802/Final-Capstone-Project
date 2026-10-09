-- Reusable views. v_active_encounters is the SINGLE filter point: soft-deleted encounters (and encounters of
-- soft-deleted patients) can never reach a KPI, API list or export because every query reads from it.
-- race and gender are deliberately NOT exposed here (they live only on patients).

-- Business question: which encounters are live, with their outcome and human-readable categories?
CREATE OR REPLACE VIEW v_active_encounters AS
SELECT
    e.encounter_id, e.patient_nbr, e.admission_date, e.discharge_date,
    e.age_group, e.age_order,
    e.admission_type_id, t.description AS admission_type,
    e.admission_source_id, s.description AS admission_source,
    e.discharge_disposition_id, d.description AS discharge_disposition, d.is_expired_or_hospice,
    sp.name AS medical_specialty, py.payer_code,
    e.time_in_hospital, e.num_lab_procedures, e.num_procedures, e.num_medications,
    e.number_outpatient, e.number_emergency, e.number_inpatient, e.number_diagnoses,
    e.max_glu_serum, e.a1c_result, e.med_changed, e.diabetes_med, e.source_batch_id,
    o.readmitted, o.readmitted_30d, o.any_readmission, o.is_readmission_eligible
FROM encounters e
JOIN encounter_outcomes o ON o.encounter_id = e.encounter_id
JOIN ref_admission_type t ON t.id = e.admission_type_id
JOIN ref_admission_source s ON s.id = e.admission_source_id
JOIN ref_discharge_disposition d ON d.id = e.discharge_disposition_id
LEFT JOIN ref_medical_specialty sp ON sp.specialty_id = e.specialty_id
LEFT JOIN ref_payer py ON py.payer_id = e.payer_id
WHERE e.is_deleted = 0
  -- anti-join instead of JOIN patients: the optimizer scans encounters first (see docs/performance_notes.md)
  AND NOT EXISTS (SELECT 1 FROM patients p WHERE p.patient_nbr = e.patient_nbr AND p.is_deleted = 1);

-- Business question: which encounters can count in the denominator of a readmission rate?
-- (expired and hospice discharges could not be readmitted, so they are excluded.)
CREATE OR REPLACE VIEW v_readmission_base AS
SELECT * FROM v_active_encounters WHERE is_readmission_eligible = 1;

