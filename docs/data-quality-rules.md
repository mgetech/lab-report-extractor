# Data-Quality Rules

Rules a record must satisfy to be trusted without a human looking at it. Owned by
`schema.py` (shape), `transform.py` (normalization), `validate.py` (routing +
plausibility), run in that order on every extraction.

## Mandatory fields

Enforced by Pydantic (`schema.py`) — missing any of these fails validation before the
record is transformed, validated, or persisted:

| Field | Model |
|---|---|
| `patient.patient_id`, `patient.name` | `Patient` |
| `analyte`, `value`, `confidence` | `Result` |
| `source_file`, `extraction_model`, `extracted_at` | `LabReport` |

Everything else (`dob`, `sex`, `ordering_physician`, `report_date`, `unit`,
`ref_range_raw`, `printed_flag`, ...) is optional — the source document may genuinely
omit it (e.g. `doc09` prints no ordering physician), and treating it as mandatory would
flag every clean document for review with no benefit.

## Value ranges & the plausibility check

The core medical-safety rule (`validate.py`): recompute the normal/abnormal flag from
value vs. reference range and compare it to the flag printed on the document. A
mismatch forces `needs_review = true` regardless of confidence.

- Ranges are parsed by a tolerant parser (`transform.parse_reference_range`) covering
  hyphen/en/em-dash, `to`-separated, split low/high, and one-sided `>`/`<`/`≥`/`≤`
  bounds — load-bearing, since the plausibility check can't recompute a flag without it.
- A value beyond the range by >20% (`_CRITICAL_HIGH_MARGIN`/`_CRITICAL_LOW_MARGIN`) is
  `HH`/`LL` rather than `H`/`L`, matching the doc's doubled-glyph convention.
- Unresolvable range (both bounds `None`) → check is skipped, not guessed.
- **Proven, not claimed:** `doc09_rows_adversarial` prints Glucose `145.0` against a
  `70-100` range but flags it `N`; the recomputed `H` disagrees and forces review. And
  `doc05`'s doubled arrow (`↑↑`), misread by Azure DI as `[11]`, still forces review
  since the recompute doesn't depend on what glyph DI saw (see `prompt-engineering.md`).

## Unit consistency

`transform.normalize_unit` checks a result's unit against a known set per canonical
analyte, normalizing notation (`mg/dl` → `mg/dL`) but never converting between systems.
An unrecognized unit forces `needs_review` rather than assuming a conversion.

## Analyte identity

`analyte` stays an open string, canonicalized via a synonym→canonical map
(`transform._ANALYTE_SYNONYMS`), never a closed enum — an unrecognized name passes
through unchanged rather than being rejected, so a new lab's naming never breaks
extraction.

## Confidence routing

| Tier | Threshold | Outcome |
|---|---|---|
| high | `>= 0.85` | Auto-accepted. |
| medium | `>= 0.60` | Accepted, flagged for review. |
| low | `< 0.60` | Routed to review — never auto-accepted. |

`LabReport.needs_review` is the OR of every result's `needs_review` (confidence tier +
plausibility mismatch + unit mismatch), so any consumer checks one flag per report.