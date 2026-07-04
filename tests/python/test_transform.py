from datetime import date, datetime

import pytest
from schema import Diagnosis, Flag, LabReport, Patient, Result, Sex
from transform import (
    canonicalize_analyte,
    normalize_unit,
    parse_numeric,
    parse_reference_range,
    transform_report,
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


# --- canonicalize_analyte -------------------------------------------------


@pytest.mark.parametrize(
    "printed,expected",
    [
        ("Hemoglobin", "Hemoglobin"),
        ("Hgb", "Hemoglobin"),
        ("HGB", "Hemoglobin"),
        ("  hgb  ", "Hemoglobin"),
        ("NA+", "Sodium"),
        ("LEUKOCYTES", "White Blood Cell Count"),
        ("CHOLESTEROL, TOTAL", "Total Cholesterol"),
    ],
)
def test_canonicalize_analyte_maps_known_synonyms(printed, expected):
    assert canonicalize_analyte(printed) == expected


def test_canonicalize_analyte_passes_through_unknown_name():
    assert canonicalize_analyte("Vitamin D, 25-Hydroxy") == "Vitamin D, 25-Hydroxy"


# --- normalize_unit --------------------------------------------------------


def test_normalize_unit_fixes_casing_for_known_unit():
    unit, mismatch = normalize_unit("Hemoglobin", "g/dl")
    assert unit == "g/dL"
    assert mismatch is False


def test_normalize_unit_accepts_si_variant():
    unit, mismatch = normalize_unit("Glucose", "mmol/L")
    assert unit == "mmol/L"
    assert mismatch is False


def test_normalize_unit_flags_unrecognized_unit():
    unit, mismatch = normalize_unit("Hemoglobin", "furlongs/fortnight")
    assert unit == "furlongs/fortnight"
    assert mismatch is True


def test_normalize_unit_passes_through_unknown_analyte():
    unit, mismatch = normalize_unit("Vitamin D, 25-Hydroxy", "ng/mL")
    assert unit == "ng/mL"
    assert mismatch is False


def test_normalize_unit_handles_none():
    assert normalize_unit("Hemoglobin", None) == (None, False)


# --- parse_numeric -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("14.2", 14.2),
        ("1,234.5", 1234.5),
        ("<0.5", 0.5),
        (">100", 100.0),
        ("-3.1", -3.1),
        ("no number here", None),
    ],
)
def test_parse_numeric(raw, expected):
    result = parse_numeric(raw)
    assert result == expected if expected is None else result == pytest.approx(expected)


# --- parse_reference_range -----------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("13.5-17.5", (13.5, 17.5)),
        ("13.5–17.5", (13.5, 17.5)),  # en dash
        ("13.5—17.5", (13.5, 17.5)),  # em dash
        ("13.5 to 17.5", (13.5, 17.5)),
        ("13.5, 17.5", (13.5, 17.5)),  # split low-high reconstructed with a comma
        ("13.5 / 17.5", (13.5, 17.5)),  # split low-high reconstructed with a slash
        (">40", (40.0, None)),
        ("<200", (None, 200.0)),
        ("≥40", (40.0, None)),
        ("≤200", (None, 200.0)),
        (None, (None, None)),
        ("", (None, None)),
        ("not a range", (None, None)),
    ],
)
def test_parse_reference_range(raw, expected):
    assert parse_reference_range(raw) == expected


def test_parse_reference_range_orders_low_high_regardless_of_print_order():
    assert parse_reference_range("17.5-13.5") == (13.5, 17.5)


# --- transform_report ------------------------------------------------------


def test_transform_report_canonicalizes_analyte_and_parses_range():
    report = _report(
        [
            Result(
                analyte="Hgb",
                value="14.2",
                unit="g/dl",
                ref_range_raw="13.5-17.5",
                printed_flag=Flag.NORMAL,
                confidence=0.9,
            )
        ]
    )

    transformed = transform_report(report)
    result = transformed.results[0]

    assert result.analyte == "Hemoglobin"
    assert result.unit == "g/dL"
    assert result.ref_low == 13.5
    assert result.ref_high == 17.5
    assert result.needs_review is False


def test_transform_report_flags_unit_mismatch_for_review():
    report = _report(
        [
            Result(
                analyte="Hgb",
                value="14.2",
                unit="parsecs",
                confidence=0.9,
            )
        ]
    )

    transformed = transform_report(report)

    assert transformed.results[0].needs_review is True


def test_transform_report_handles_one_sided_range():
    report = _report(
        [
            Result(
                analyte="HDL",
                value="32",
                unit="mg/dL",
                ref_range_raw=">40",
                confidence=0.9,
            )
        ]
    )

    transformed = transform_report(report)
    result = transformed.results[0]

    assert result.analyte == "HDL Cholesterol"
    assert result.ref_low == 40.0
    assert result.ref_high is None


def test_transform_report_does_not_mutate_input():
    report = _report(
        [Result(analyte="Hgb", value="14.2", unit="g/dl", confidence=0.9)]
    )

    transform_report(report)

    assert report.results[0].analyte == "Hgb"
    assert report.results[0].unit == "g/dl"