-- Schema for the lab report extraction pipeline's system of record.
-- Applied idempotently on API startup (see DbInitializer) and safe to mount
-- unmodified into Postgres's /docker-entrypoint-initdb.d/. No migrations —
-- every statement is CREATE ... IF NOT EXISTS so re-running it is a no-op.
--
-- Deliberately two tables, not four: patient fields live as columns on
-- lab_reports (a report always carries exactly one patient, no cross-report
-- patient identity resolution in this case study), and diagnoses are a JSONB
-- column (small, schemaless free-text list, never queried on their own).
-- Results get their own table because they're the one-to-many that drives
-- the review queue.

CREATE TABLE IF NOT EXISTS lab_reports (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id          TEXT NOT NULL,
    patient_name        TEXT NOT NULL,
    patient_dob         DATE,
    patient_sex         TEXT CHECK (patient_sex IN ('M', 'F', 'O', 'U')),
    report_date         DATE,
    collection_date     DATE,
    ordering_physician  TEXT,
    lab_name            TEXT,
    source_file         TEXT NOT NULL,
    extraction_model    TEXT NOT NULL,
    extracted_at        TIMESTAMPTZ NOT NULL,
    needs_review        BOOLEAN NOT NULL DEFAULT FALSE,
    diagnoses           JSONB NOT NULL DEFAULT '[]'::JSONB
);

CREATE INDEX IF NOT EXISTS ix_lab_reports_patient_id ON lab_reports (patient_id);
CREATE INDEX IF NOT EXISTS ix_lab_reports_needs_review ON lab_reports (needs_review);

CREATE TABLE IF NOT EXISTS results (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lab_report_id   BIGINT NOT NULL REFERENCES lab_reports (id) ON DELETE CASCADE,
    analyte         TEXT NOT NULL,
    value           TEXT NOT NULL,
    unit            TEXT,
    ref_range_raw   TEXT,
    ref_low         DOUBLE PRECISION,
    ref_high        DOUBLE PRECISION,
    printed_flag    TEXT CHECK (printed_flag IN ('N', 'H', 'L', 'HH', 'LL')),
    computed_flag   TEXT CHECK (computed_flag IN ('N', 'H', 'L', 'HH', 'LL')),
    confidence      DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_results_lab_report_id ON results (lab_report_id);
CREATE INDEX IF NOT EXISTS ix_results_needs_review ON results (needs_review);