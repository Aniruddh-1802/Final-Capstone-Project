"""Core handle for the v_active_encounters view: THE single read path for encounters.

Soft-deleted encounters (and encounters of soft-deleted patients) are excluded by the view itself, so every list,
detail read and analytics query that selects from ``V`` inherits the filter. race/gender are not in the view.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Date, Integer, String, column, table

V = table(
    "v_active_encounters",
    column("encounter_id", Integer), column("patient_nbr", Integer),
    column("admission_date", Date), column("discharge_date", Date),
    column("age_group", String), column("age_order", Integer),
    column("admission_type_id", Integer), column("admission_type", String),
    column("admission_source_id", Integer), column("admission_source", String),
    column("discharge_disposition_id", Integer), column("discharge_disposition", String),
    column("is_expired_or_hospice", Boolean), column("medical_specialty", String), column("payer_code", String),
    column("time_in_hospital", Integer), column("num_lab_procedures", Integer), column("num_procedures", Integer),
    column("num_medications", Integer), column("number_outpatient", Integer), column("number_emergency", Integer),
    column("number_inpatient", Integer), column("number_diagnoses", Integer),
    column("max_glu_serum", String), column("a1c_result", String), column("med_changed", Boolean),
    column("diabetes_med", Boolean), column("source_batch_id", String),
    column("readmitted", String), column("readmitted_30d", Boolean), column("any_readmission", Boolean),
    column("is_readmission_eligible", Boolean),
)
