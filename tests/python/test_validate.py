from datetime import date, datetime

import pytest
from schema import Diagnosis, Flag, LabReport, Patient, Result, Sex
from validate import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    confidence_tier,
    recompute_flag,
    validate_report,
)


def _report(results: list[Result]) -> LabReport:
    return LabReport(
        source_file="sample.pdf",
        extraction_model="gpt-5-mini",
        extracted_at=datetime(2026, 7, 4, 12, 0, 0),
        patient=Patient(patient_id="P-001", name="Jane Doe", dob=date(1990, 1, 1), sex=Sex.FEMALE),
        results=results,
        diagnoses=[Diagnosis(text="Routine checkup", confidence=0.9)],
    )


def _result(**overrides) -> Result:
    defaults = dict(
        analyte="Hemoglobin",
        value="14.2",
        unit="g/dL",
        ref_low=13.5,
        ref_high=17.5,
        printed_flag=Flag.NORMAL,
        confidence=0.95,
    )
    defaults.update(overrides)
    return Result(**defaults)


# --- confidence_tier -------------------------------------------------------


def test_confidence_tier_boundaries():
    assert confidence_tier(HIGH_CONFIDENCE_THRESHOLD) == "high"
    assert confidence_tier(HIGH_CONFIDENCE_THRESHOLD - 0.01) == "medium"
    assert confidence_tier(MEDIUM_CONFIDENCE_THRESHOLD) == "medium"
    assert confidence_tier(MEDIUM_CONFIDENCE_THRESHOLD - 0.01) == "low"
    assert confidence_tier(1.0) == "high"
    assert confidence_tier(0.0) == "low"


# --- recompute_flag ---------------------------------------------------------


@pytest.mark.parametrize(
    "value,ref_low,ref_high,expected",
    [
        (14.2, 13.5, 17.5, Flag.NORMAL),
        (11.0, 13.5, 17.5, Flag.LOW),
        (19.0, 13.5, 17.5, Flag.HIGH),
        (5.0, 13.5, 17.5, Flag.CRITICAL_LOW),  # < ref_low * 0.8
        (25.0, 13.5, 17.5, Flag.CRITICAL_HIGH),  # > ref_high * 1.2
        (32.0, 40.0, None, Flag.LOW),  # one-sided lower bound (HDL-style)
        (230.0, None, 200.0, Flag.HIGH),  # one-sided upper bound (cholesterol-style)
        (100.0, None, None, None),  # no bounds -> can't compute
    ],
)
def test_recompute_flag(value, ref_low, ref_high, expected):
    assert recompute_flag(value, ref_low, ref_high) == expected


# --- validate_report: confidence routing -----------------------------------


def test_high_confidence_result_not_flagged():
    report = _report([_result(confidence=0.95)])
    validated = validate_report(report)
    assert validated.results[0].needs_review is False
    assert validated.needs_review is False


def test_medium_confidence_result_flagged_for_review():
    report = _report([_result(confidence=0.70)])
    validated = validate_report(report)
    assert validated.results[0].needs_review is True
    assert validated.needs_review is True


def test_low_confidence_result_never_auto_accepted():
    report = _report([_result(confidence=0.20)])
    validated = validate_report(report)
    assert validated.results[0].needs_review is True


# --- validate_report: plausibility check ------------------------------------


def test_plausibility_agreement_does_not_force_review():
    report = _report([_result(value="14.2", ref_low=13.5, ref_high=17.5, printed_flag=Flag.NORMAL)])
    validated = validate_report(report)
    assert validated.results[0].computed_flag == Flag.NORMAL
    assert validated.results[0].needs_review is False


def test_plausibility_disagreement_forces_review_even_at_high_confidence():
    # Adversarial case: glucose is clearly high vs. its range but the page prints "N".
    report = _report(
        [
            _result(
                analyte="Glucose",
                value="112",
                ref_low=70.0,
                ref_high=100.0,
                printed_flag=Flag.NORMAL,
                confidence=0.99,
            )
        ]
    )
    validated = validate_report(report)
    assert validated.results[0].computed_flag == Flag.HIGH
    assert validated.results[0].needs_review is True
    assert validated.needs_review is True


def test_plausibility_skipped_when_ranges_are_unparsed():
    report = _report([_result(ref_low=None, ref_high=None, confidence=0.95)])
    validated = validate_report(report)
    assert validated.results[0].computed_flag is None
    assert validated.results[0].needs_review is False


def test_plausibility_skipped_when_value_is_unparseable():
    report = _report([_result(value="not a number", confidence=0.95)])
    validated = validate_report(report)
    assert validated.results[0].computed_flag is None
    assert validated.results[0].needs_review is False


def test_report_needs_review_is_or_of_all_results():
    report = _report(
        [
            _result(analyte="Hemoglobin", confidence=0.95),
            _result(analyte="Glucose", confidence=0.20),
        ]
    )
    validated = validate_report(report)
    assert validated.results[0].needs_review is False
    assert validated.results[1].needs_review is True
    assert validated.needs_review is True


def test_validate_report_does_not_mutate_input():
    report = _report([_result(confidence=0.20)])
    validate_report(report)
    assert report.results[0].needs_review is False
    assert report.needs_review is False