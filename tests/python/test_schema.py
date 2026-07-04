from datetime import date, datetime

import pytest
from pydantic import ValidationError

from schema import Diagnosis, Flag, Gender, LabReport, Patient, Result


def _sample_report() -> LabReport:
    return LabReport(
        source_file="sample.pdf",
        extraction_model="gpt-5-mini",
        extracted_at=datetime(2026, 7, 4, 12, 0, 0),
        report_date=date(2026, 7, 3),
        collection_date=date(2026, 7, 2),
        ordering_physician="Dr. Smith",
        lab_name="Acme Labs",
        patient=Patient(patient_id="P-001", name="Jane Doe", dob=date(1990, 1, 1), gender=Gender.FEMALE),
        results=[
            Result(
                analyte="Hemoglobin",
                value="14.2",
                unit="g/dL",
                ref_range_raw="13.5-17.5",
                ref_low=13.5,
                ref_high=17.5,
                printed_flag=Flag.NORMAL,
                confidence=0.97,
            )
        ],
        diagnoses=[Diagnosis(text="Routine checkup - no abnormalities", confidence=0.9)],
    )


def test_lab_report_round_trips_through_json():
    report = _sample_report()
    restored = LabReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_confidence_out_of_range_is_rejected():
    with pytest.raises(ValidationError):
        Result(analyte="Hemoglobin", value="14.2", confidence=1.5)


def test_needs_review_defaults_false():
    report = _sample_report()
    assert report.needs_review is False
    assert report.results[0].needs_review is False


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Patient(patient_id="P-001", name="Jane Doe", unexpected_field="oops")
