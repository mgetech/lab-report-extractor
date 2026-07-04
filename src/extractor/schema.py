"""Pydantic v2 schema for the extraction engine's structured output: one
`LabReport` per document, with patient demographics, result rows, free-text
diagnoses, provenance and confidence-driven review routing.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Sex(StrEnum):
    MALE = "M"
    FEMALE = "F"
    OTHER = "O"
    UNKNOWN = "U"


class Flag(StrEnum):
    """Printed or recomputed normal/abnormal flag."""

    NORMAL = "N"
    HIGH = "H"
    LOW = "L"
    CRITICAL_HIGH = "HH"
    CRITICAL_LOW = "LL"


class Patient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    name: str
    dob: date | None = None
    sex: Sex | None = None


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confidence: float = Field(ge=0.0, le=1.0)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analyte: str
    value: str
    unit: str | None = None
    ref_range_raw: str | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    printed_flag: Flag | None = None
    computed_flag: Flag | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_review: bool = False


class LabReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_file: str
    extraction_model: str
    extracted_at: datetime
    report_date: date | None = None
    collection_date: date | None = None
    ordering_physician: str | None = None
    lab_name: str | None = None
    needs_review: bool = False

    patient: Patient
    results: list[Result] = Field(default_factory=list)
    diagnoses: list[Diagnosis] = Field(default_factory=list)
