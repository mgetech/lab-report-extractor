"""Azure OpenAI client: structures Document Intelligence layout output into the
`LabReport` schema via structured outputs.

The prompt carries only DI's plain-text content and rendered tables -- never its
per-word/line confidence payload, which is pure token bloat the LLM can't use to
map fields onto the schema. Per-field confidence is instead computed here, after
the LLM responds, by matching each extracted value back to DI's word confidences
(falling back to the document's mean word confidence when no match is found) --
lean prompt tokens without losing the confidence signal medical-safety routing
needs.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from di_client import LayoutResult, Table
from schema import Diagnosis, Flag, LabReport, Patient, Result

logger = logging.getLogger(__name__)


class LLMExtractionError(Exception):
    """Raised when the Azure OpenAI call fails or the model returns no parsed content.

    Callers (batch.py) catch this to log, skip, and continue rather than crash the batch.
    """


class _ExtractedResult(BaseModel):
    """LLM wire shape for one result row: content only. `confidence` is computed in
    code from DI word confidences; `ref_low`/`ref_high` are left for transform.py's
    tolerant range parser (Day 2) rather than guessed here."""

    model_config = ConfigDict(extra="forbid")

    analyte: str
    value: str
    unit: str | None = None
    ref_range_raw: str | None = None
    printed_flag: Flag | None = None


class _ExtractedDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str


class _ExtractedLabReport(BaseModel):
    """LLM wire shape for one document: excludes provenance (source_file/
    extraction_model/extracted_at), confidence, and needs_review -- those are
    filled in by code, not the model."""

    model_config = ConfigDict(extra="forbid")

    report_date: date | None = None
    collection_date: date | None = None
    ordering_physician: str | None = None
    lab_name: str | None = None
    patient: Patient
    results: list[_ExtractedResult] = Field(default_factory=list)
    diagnoses: list[_ExtractedDiagnosis] = Field(default_factory=list)


_TERSE_PROMPT = """\
You are a medical lab report data extraction assistant. Extract the patient, report, \
result, and diagnosis fields from the OCR text and tables below onto the given schema. \
Don't invent values that aren't present in the text. A blank/absent printed flag means \
the result is NORMAL ("N"), never null. Convert dates to ISO 8601 (YYYY-MM-DD).
"""

_SCHEMA_ANNOTATED_PROMPT = """\
You are a medical lab report data extraction assistant. You are given the plain-text \
content and tables read from a lab report by an OCR/layout engine. Map what you find \
onto the given schema exactly -- do not invent, infer, or calculate values that are not \
present in the text.

Rules:
- `analyte`: the test name exactly as printed (do not normalize, translate, or expand it).
- `value`: the printed result exactly as printed.
- `ref_range_raw`: the printed reference range exactly as printed (e.g. "13.5-17.5", ">40", \
"<200"); null if none is printed.
- `printed_flag`: the printed abnormal-result flag, mapped to one of N, H, L, HH, LL \
(covering letter, arrow, or asterisk notations). Lab reports only print a flag for \
abnormal results -- a blank/absent flag means the result is NORMAL, so set `printed_flag` \
to "N" in that case; never leave it null just because nothing was printed next to the value.
- `patient.sex`: map to one of M, F, O, U.
- Dates (`report_date`, `collection_date`, `patient.dob`): convert the printed date to ISO \
8601 (YYYY-MM-DD), regardless of how it's printed on the document (e.g. DD.MM.YYYY or \
MM/DD/YYYY).
- A doubled/repeated flag symbol means the CRITICAL variant, not a second instance of the \
same flag: "**" is critical (HH if the value is high, LL if low), "↑↑" is HH, "↓↓" is LL -- \
map these to HH/LL, never to a plain H/L.
- If a field is genuinely absent from the document, leave it null (or omit it from the \
results/diagnoses list) rather than guessing.
"""

_FEW_SHOT_PROMPT = (
    _SCHEMA_ANNOTATED_PROMPT
    + """
Example:

Document text:
Patient: Alex Rivera (DOB 04.11.1990, M)  Report Date: 12.06.2026
Hemoglobin 13.1 g/dL (13.5-17.5)
Glucose 210 mg/dL (70-100) [H]
WBC 22.0 x10^9/L (4.0-11.0) [**]
Diagnosis: Hyperglycemia, recommend follow-up

Correct extraction (illustrating the rules above, not the full schema):
- patient.dob = "1990-11-04" (DD.MM.YYYY converted to ISO 8601)
- report_date = "2026-06-12"
- Hemoglobin: value="13.1", ref_range_raw="13.5-17.5", printed_flag="N" (nothing was \
printed next to it, which means normal -- not null)
- Glucose: value="210", ref_range_raw="70-100", printed_flag="H" (printed flag preserved \
as-is)
- WBC: value="22.0", ref_range_raw="4.0-11.0", printed_flag="HH" (doubled "**" means \
critical-high, not a plain "H")
- diagnoses: ["Hyperglycemia, recommend follow-up"]
"""
)

_SYSTEM_PROMPTS: dict[str, str] = {
    "terse": _TERSE_PROMPT,
    "schema_annotated": _SCHEMA_ANNOTATED_PROMPT,
    "few_shot": _FEW_SHOT_PROMPT,
}

DEFAULT_PROMPT_VARIANT = "schema_annotated"
"""Current production default, pending the sweep in docs/prompt-engineering.md -- updated
to the winner once results are in."""


def _render_tables(tables: list[Table]) -> str:
    blocks = []
    for i, table in enumerate(tables, start=1):
        grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
        for cell in table.cells:
            grid[cell.row_index][cell.column_index] = cell.content
        rows = ["| " + " | ".join(row) + " |" for row in grid]
        blocks.append(f"Table {i}:\n" + "\n".join(rows))
    return "\n\n".join(blocks)


def _build_user_prompt(layout: LayoutResult) -> str:
    sections = [f"Document text:\n{layout.content}"]
    if layout.tables:
        sections.append(f"Tables:\n{_render_tables(layout.tables)}")
    return "\n\n".join(sections)


def _document_mean_confidence(layout: LayoutResult) -> float:
    confidences = [word.confidence for page in layout.pages for word in page.words]
    return sum(confidences) / len(confidences) if confidences else 0.0


def _matched_confidence(text: str, layout: LayoutResult, fallback: float) -> float:
    """Confidence for one extracted value: mean confidence of the DI words whose
    content exactly matches `text` (case/whitespace-insensitive), or `fallback`
    (the document's mean word confidence) if none match."""
    normalized = text.strip().lower()
    if not normalized:
        return fallback
    matched = [
        word.confidence
        for page in layout.pages
        for word in page.words
        if word.content.strip().lower() == normalized
    ]
    return sum(matched) / len(matched) if matched else fallback


class LLMClient:
    """Thin wrapper over an Azure OpenAI (Foundry) chat deployment: structures DI's
    layout output into a validated `LabReport`."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        deployment: str,
        prompt_variant: str = DEFAULT_PROMPT_VARIANT,
    ) -> None:
        # This project's Azure OpenAI resource is called through the newer
        # OpenAI-compatible v1 API surface (endpoint already ends in `/openai/v1`,
        # GA since Aug 2025) -- so the plain `OpenAI` client with `base_url` is
        # correct here, not `AzureOpenAI`/`azure_endpoint`, which targets the
        # older deployment-path routing and 404s against a v1 endpoint.
        self._client = OpenAI(base_url=endpoint, api_key=api_key)
        self._deployment = deployment
        try:
            self._system_prompt = _SYSTEM_PROMPTS[prompt_variant]
        except KeyError:
            raise ValueError(
                f"Unknown prompt_variant {prompt_variant!r}; "
                f"expected one of {sorted(_SYSTEM_PROMPTS)}"
            ) from None

    def ping(self) -> None:
        """Cheap reachability check for `/ready`: lists available models rather than
        running a real completion, so it spends no completion tokens.

        Raises `LLMExtractionError` if the endpoint is unreachable or the key is invalid.
        """
        try:
            self._client.models.list()
        except OpenAIError as exc:
            logger.error("Azure OpenAI readiness check failed: %s", exc)
            raise LLMExtractionError(str(exc)) from exc

    def extract(self, layout: LayoutResult, source_file: str) -> LabReport:
        """Structure one document's DI layout output into a validated `LabReport`.

        Raises `LLMExtractionError` on an Azure OpenAI failure or a response with no
        parsed content; never lets the underlying SDK exception escape.
        """
        try:
            completion = self._client.chat.completions.parse(
                model=self._deployment,
                messages=[
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": _build_user_prompt(layout)},
                ],
                response_format=_ExtractedLabReport,
                max_completion_tokens=4096,
            )
        except OpenAIError as exc:
            logger.error("Azure OpenAI extraction failed: %s", exc)
            raise LLMExtractionError(str(exc)) from exc

        message = completion.choices[0].message
        if message.parsed is None:
            raise LLMExtractionError(message.refusal or "model returned no parsed content")

        return self._to_lab_report(message.parsed, layout, source_file)

    def _to_lab_report(
        self, extracted: _ExtractedLabReport, layout: LayoutResult, source_file: str
    ) -> LabReport:
        doc_mean = _document_mean_confidence(layout)
        results = [
            Result(
                analyte=r.analyte,
                value=r.value,
                unit=r.unit,
                ref_range_raw=r.ref_range_raw,
                printed_flag=r.printed_flag,
                confidence=_matched_confidence(r.value, layout, doc_mean),
            )
            for r in extracted.results
        ]
        diagnoses = [
            Diagnosis(text=d.text, confidence=_matched_confidence(d.text, layout, doc_mean))
            for d in extracted.diagnoses
        ]
        return LabReport(
            source_file=source_file,
            extraction_model=self._deployment,
            extracted_at=datetime.now(UTC),
            report_date=extracted.report_date,
            collection_date=extracted.collection_date,
            ordering_physician=extracted.ordering_physician,
            lab_name=extracted.lab_name,
            patient=extracted.patient,
            results=results,
            diagnoses=diagnoses,
        )
