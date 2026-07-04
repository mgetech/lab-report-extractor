"""Normalization pass applied after LLM extraction, before validation/routing.

What *does* land here:
- `analyte` canonicalization via an open synonym map (never a closed enum -- an enum is
  what silently breaks the moment a new lab prints a name we haven't seen).
- `unit` notation normalization, and flagging (not converting) units outside the analyte's
  known set -- e.g. a printed `mg/dl` becomes `mg/dL`, but an unrecognized unit routes the
  result to review instead of guessing a conversion.
- A tolerant reference-range parser for `ref_range_raw` -> `ref_low`/`ref_high`, covering
  hyphen/en-dash/em-dash ranges, one-sided `>`/`<` bounds, and split low-high text. This is
  load-bearing: validate.py's plausibility check can't recompute the H/L flag without it.
- `parse_numeric`: strips comparison qualifiers/thousands separators from `Result.value` so
  validate.py can compare it against `ref_low`/`ref_high`.
"""

from __future__ import annotations

import re

from schema import LabReport, Result

# Canonical name -> every printed synonym we've seen (case/whitespace-insensitive lookup
# built from these at import time). New synonyms are additive; an analyte missing from
# this map passes through unchanged rather than being rejected.
_ANALYTE_SYNONYMS: dict[str, list[str]] = {
    "Hemoglobin": ["Hemoglobin", "Hgb", "HGB", "Hb"],
    "White Blood Cell Count": ["White Blood Cell Count", "WBC", "LEUKOCYTES"],
    "Glucose": ["Glucose", "GLU", "BLOOD SUGAR"],
    "Creatinine": ["Creatinine", "Creat", "CREA"],
    "Sodium": ["Sodium", "Na", "NA+"],
    "Potassium": ["Potassium", "K", "K+"],
    "Alanine Aminotransferase": ["Alanine Aminotransferase", "ALT", "SGPT"],
    "Total Cholesterol": ["Total Cholesterol", "Chol", "CHOLESTEROL, TOTAL"],
    "HDL Cholesterol": ["HDL Cholesterol", "HDL", "HDL-C"],
    "Thyroid Stimulating Hormone": ["Thyroid Stimulating Hormone", "TSH"],
}

# Canonical name -> acceptable printed units (US + SI variants). Used only to flag an
# unrecognized unit for review -- never to convert a value between systems.
_ANALYTE_UNITS: dict[str, list[str]] = {
    "Hemoglobin": ["g/dL", "g/L"],
    "White Blood Cell Count": ["x10^3/uL", "x10^9/L"],
    "Glucose": ["mg/dL", "mmol/L"],
    "Creatinine": ["mg/dL", "umol/L"],
    "Sodium": ["mEq/L", "mmol/L"],
    "Potassium": ["mEq/L", "mmol/L"],
    "Alanine Aminotransferase": ["U/L"],
    "Total Cholesterol": ["mg/dL", "mmol/L"],
    "HDL Cholesterol": ["mg/dL", "mmol/L"],
    "Thyroid Stimulating Hormone": ["mIU/L"],
}


def _lookup_key(text: str) -> str:
    """Case/punctuation-insensitive key: lowercase, collapse non-alphanumerics to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


_ANALYTE_ALIASES: dict[str, str] = {
    _lookup_key(synonym): canonical
    for canonical, synonyms in _ANALYTE_SYNONYMS.items()
    for synonym in synonyms
}

_UNIT_ALIASES: dict[str, dict[str, str]] = {
    canonical: {_lookup_key(unit): unit for unit in units}
    for canonical, units in _ANALYTE_UNITS.items()
}


def canonicalize_analyte(name: str) -> str:
    """Map a printed analyte name to its canonical form via the synonym table.

    Unrecognized names pass through unchanged (stripped) -- `analyte` stays an open
    string, so a new lab's naming never breaks extraction.
    """
    return _ANALYTE_ALIASES.get(_lookup_key(name), name.strip())


def normalize_unit(canonical_analyte: str, unit: str | None) -> tuple[str | None, bool]:
    """Normalize a printed unit's notation and report whether it's unrecognized.

    Returns `(normalized_unit, mismatch)`. `mismatch` is True when `unit` doesn't match
    any known unit (US or SI) for this analyte -- callers should route that result to
    review rather than silently trusting or converting it.
    """
    if unit is None:
        return None, False
    known = _UNIT_ALIASES.get(canonical_analyte)
    if known is None:
        return unit.strip(), False
    canonical_unit = known.get(_lookup_key(unit))
    if canonical_unit is None:
        return unit.strip(), True
    return canonical_unit, False


_NUMERIC_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


def parse_numeric(value: str) -> float | None:
    """Extract a float from a printed result value.

    Strips comparison qualifiers (`<0.5` -> 0.5) and thousand separators (`1,234.5` ->
    1234.5). Returns None if no number is found, rather than raising -- an unparseable
    value is a validation concern (route to review), not a transform-time crash.
    """
    match = _NUMERIC_PATTERN.search(value)
    if match is None:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


# Matches one-sided bounds: a leading <, >, <=, >=, ≤, or ≥ followed by a number.
_ONE_SIDED_PATTERN = re.compile(r"^\s*(<=|>=|<|>|≤|≥)\s*([-+]?\d+(?:\.\d+)?)\s*$")

# Matches a two-sided range: two numbers separated by a hyphen, en-dash, em-dash, "to",
# comma, or slash -- covering both combined ("13.5-17.5") and reconstructed split
# low/high column text.
_RANGE_PATTERN = re.compile(
    r"^\s*([-+]?\d+(?:\.\d+)?)\s*(?:-|–|—|to|,|/)\s*([-+]?\d+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def parse_reference_range(raw: str | None) -> tuple[float | None, float | None]:
    """Tolerant parser for a printed reference range -> `(ref_low, ref_high)`.

    Handles `13.5-17.5`, `13.5–17.5` (en dash), `13.5—17.5` (em dash), `13.5 to 17.5`,
    split low-high text (`13.5, 17.5` / `13.5 / 17.5`), and one-sided bounds (`>40` ->
    `(40, None)`, `<200` -> `(None, 200)`). Returns `(None, None)` when `raw` is absent
    or doesn't match a known shape -- callers should treat that as "can't compute a
    plausibility check for this result", not guess.
    """
    if raw is None or not raw.strip():
        return None, None

    one_sided = _ONE_SIDED_PATTERN.match(raw)
    if one_sided:
        operator, number = one_sided.groups()
        bound = float(number)
        return (bound, None) if operator in (">", ">=", "≥") else (None, bound)

    two_sided = _RANGE_PATTERN.match(raw)
    if two_sided:
        low, high = (float(n) for n in two_sided.groups())
        return (low, high) if low <= high else (high, low)

    return None, None


def _transform_result(result: Result) -> Result:
    canonical_analyte = canonicalize_analyte(result.analyte)
    normalized_unit, unit_mismatch = normalize_unit(canonical_analyte, result.unit)
    ref_low, ref_high = parse_reference_range(result.ref_range_raw)
    return result.model_copy(
        update={
            "analyte": canonical_analyte,
            "unit": normalized_unit,
            "ref_low": ref_low,
            "ref_high": ref_high,
            "needs_review": result.needs_review or unit_mismatch,
        }
    )


def transform_report(report: LabReport) -> LabReport:
    """Apply analyte canonicalization, unit normalization, and reference-range parsing
    to every result in `report`. Returns a new `LabReport`; does not mutate the input.
    """
    return report.model_copy(update={"results": [_transform_result(r) for r in report.results]})
