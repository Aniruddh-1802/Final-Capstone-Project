-- Secondary indexes added in L12. Each is justified by an EXPLAIN plan in docs/performance_notes.md and mirrored in the
-- SQLAlchemy models (a test compares the two), so databases built from the models or from schema.sql already have them.
-- Apply to an existing database with:  python scripts/apply_indexes.py   (skips indexes that already exist)
-- Indexes that were measured and rejected are listed in docs/performance_notes.md.

-- Q1/Q3: date-range lists and trends always filter is_deleted = 0 and then a range on admission_date.
CREATE INDEX ix_encounters_is_deleted_admission_date ON encounters (is_deleted, admission_date);

-- Q6: ICD-9 prefix search (LIKE 'V57%').
CREATE INDEX ix_encounter_diagnoses_icd9_code ON encounter_diagnoses (icd9_code);

-- Q5/Q8: audit lists are newest first inside a date window (a user filter is applied on the few rows the range returns).
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

-- Q9: audit trail of one record.
CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id);
