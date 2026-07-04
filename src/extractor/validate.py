"""Confidence routing + plausibility check, applied after transform.py and before
persistence. The last Python-side gate before a result is trusted -- the C# API adds a
second guard (mandatory-field checks) once the record lands there.

Confidence routing (per result), tiers documented where the thresholds are defined:
- high: auto-accept, no review flag from confidence alone.
- medium: accept, but flagged for review (still usable, just double-checked).
- low: routed to review. Never auto-accepted -- this is the hard medical-safety rule.

Plausibility check (per result): recompute the normal/abnormal flag from `value` vs.
`ref_low`/`ref_high` (parsed by transform.py) and compare to the LLM's `printed_flag`.
A disagreement forces `needs_review` regardless of confidence -- either the document
itself has a wrong printed flag, or the pipeline misread something, and either way a
human needs to look before the record is trusted.

`LabReport.needs_review` is the OR of every result's `needs_review`, so downstream
consumers only need to check one flag to know whether a report needs a human.
"""

from __future__ import annotations

from schema import Flag, LabReport, Result
from transform import parse_numeric

# Picked to keep "never auto-accept a low-confidence value" meaningful without being so
# strict that clean, high-quality DI reads get flagged for no reason. Revisit against
# eval/evaluate.py's per-field accuracy numbers once real runs exist.
HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.60

# A value beyond the reference range by more than these fractions is critical rather
# than just high/low. Mirrors sample_data/generate.py's ground-truth convention so eval
# comparisons aren't skewed by two different critical-value heuristics.
_CRITICAL_HIGH_MARGIN = 1.2
_CRITICAL_LOW_MARGIN = 0.8


def confidence_tier(confidence: float) -> str:
    """Classify a confidence score into "high" / "medium" / "low" per the module-level
    thresholds."""
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def recompute_flag(value: float, ref_low: float | None, ref_high: float | None) -> Flag | None:
    """Recompute the normal/abnormal flag from a numeric value and reference bounds.

    Either bound may be None (one-sided reference range, e.g. `<200` or `>40`, parsed by
    transform.py as `(None, 200)` / `(40, None)`). Returns None if both bounds are
    missing -- there's nothing to recompute against, so the plausibility check is
    skipped for that result rather than guessing.
    """
    if ref_low is None and ref_high is None:
        return None
    if ref_high is not None and value > ref_high:
        return Flag.CRITICAL_HIGH if value > ref_high * _CRITICAL_HIGH_MARGIN else Flag.HIGH
    if ref_low is not None and value < ref_low:
        return Flag.CRITICAL_LOW if value < ref_low * _CRITICAL_LOW_MARGIN else Flag.LOW
    return Flag.NORMAL


def _validate_result(result: Result) -> Result:
    tier = confidence_tier(result.confidence)

    value = parse_numeric(result.value)
    computed_flag = (
        recompute_flag(value, result.ref_low, result.ref_high) if value is not None else None
    )
    flag_mismatch = (
        computed_flag is not None
        and result.printed_flag is not None
        and computed_flag != result.printed_flag
    )

    needs_review = result.needs_review or tier != "high" or flag_mismatch
    return result.model_copy(update={"computed_flag": computed_flag, "needs_review": needs_review})


def validate_report(report: LabReport) -> LabReport:
    """Apply confidence routing and the plausibility check to every result in `report`.

    Returns a new `LabReport` with each result's `computed_flag`/`needs_review` set, and
    the report-level `needs_review` OR'd in from every result. Does not mutate the input.
    """
    results = [_validate_result(r) for r in report.results]
    return report.model_copy(
        update={
            "results": results,
            "needs_review": report.needs_review or any(r.needs_review for r in results),
        }
    )
