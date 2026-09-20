# Evaluation

Per-field, per-layout accuracy against ground truth (`eval/evaluate.py`), and the prompt
variant comparison that used the same harness to pick the production prompt
(`eval/run_prompt_sweep.py`). Both share one measurement: field-by-field match rate,
broken down per document layout so robustness across formats is shown, not claimed.

## Test documents

Nine synthetic documents (`sample_data/generate.py`), varied along named axes rather than
cosmetic restyling — table structure (`rows` / `panels` / `inline`), label synonyms
(Hemoglobin/Hgb/HGB), units, reference-range notation, date format, flag notation
(H/L / arrows / asterisk), and digital-clean vs. scanned-skewed rendering:

| Doc | Layout |
|---|---|
| doc01, doc02 | `rows_clean` |
| doc03, doc04 | `panels_clean` |
| doc05, doc06 | `inline_clean` |
| doc07 | `rows_scanned` |
| doc08 | `panels_scanned` |
| doc09 | `rows_adversarial` |

`generate.py` emits each PDF **and** its matching ground-truth JSON in the same run (the
values are authored, not guessed, so ground truth is free and exact). doc09 is the
adversarial case: it deliberately has a missing field, one out-of-range critical value,
and one wrong printed flag.

## Methodology

`eval/evaluate.py` runs the pipeline's output against `sample_data/ground_truth/` per
document, then aggregates by layout (the `docNN_` prefix stripped off, e.g.
`rows_clean`, `panels_scanned`):

- **Report-level fields** (dates, physician, lab name, patient demographics) are compared
  directly.
- **Result rows** are paired by *canonicalized* analyte name (`transform.canonicalize_analyte`),
  not by position — row order/count can legitimately differ between extraction and ground
  truth, so pairing by identity avoids penalizing a correct extraction for a reordered table.
  Ground-truth rows with no matching extraction count against `result_recall`.
- **Equality is field-aware**, not naive string match: `value`/`ref_low`/`ref_high` are
  parsed to numbers and compared with tolerance (so `"0.90"` vs `"0.9"` isn't a mismatch);
  text fields are case/whitespace-insensitive; everything else is exact.

This is the same harness used for both the production-accuracy table below and the prompt
variant sweep — one measurement, reused, so the two results are directly comparable.

## Production accuracy

Full per-layout breakdown for the production prompt (`schema_annotated`), 9 documents /
6 layouts ([full table](../eval/results.md)):

| Field | inline_clean | panels_clean | panels_scanned | rows_adversarial | rows_clean | rows_scanned | Overall |
|---|---|---|---|---|---|---|---|
| report_date | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| collection_date | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| ordering_physician | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| lab_name | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| patient.patient_id | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| patient.name | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| patient.dob | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| patient.sex | 2/2 (100%) | 2/2 (100%) | 1/1 (100%) | 1/1 (100%) | 2/2 (100%) | 1/1 (100%) | 9/9 (100%) |
| value | 10/10 (100%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 45/45 (100%) |
| unit | 10/10 (100%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 45/45 (100%) |
| ref_low | 10/10 (100%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 45/45 (100%) |
| ref_high | 10/10 (100%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 45/45 (100%) |
| printed_flag | 9/10 (90%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 44/45 (98%) |
| result_recall | 10/10 (100%) | 12/12 (100%) | 4/4 (100%) | 4/4 (100%) | 10/10 (100%) | 5/5 (100%) | 45/45 (100%) |

Every field is 100% except `printed_flag` at 98% — one miss, `inline_clean`, traced below.

## Prompt variant comparison

Three system-prompt variants for `llm_client.py`'s structuring call were run across the
same 9 documents / 6 layouts, scored with the same harness. `di_client.py`'s output
doesn't depend on the LLM prompt, so the sweep runs Document Intelligence once per
document and reuses the layout across all three variants — only the LLM call varies.

| Variant | Description |
|---|---|
| `terse` | One short paragraph: map fields onto the schema, blank flag = normal, dates to ISO 8601. No per-field rules. |
| `schema_annotated` | Field-by-field rules (production default) — how to read `analyte`/`value`/`ref_range_raw`, the blank-flag-means-normal rule, date conversion, and a rule for doubled/repeated flag glyphs (`**` / `↑↑` / `↓↓`) meaning the *critical* variant (HH/LL), not a second plain flag. |
| `few_shot` | `schema_annotated` plus one worked example demonstrating a blank flag, a plain flag, and a doubled flag glyph together. |

### Why a doubled-flag rule exists at all

`sample_data/generate.py` renders a *critical* result as a doubled glyph for non-letter
flag styles — `↑↑`/`↓↓` for arrows, `**` for asterisk (a plain `H`/`L` is a single glyph;
`HH`/`LL` critical results double it, matching real report conventions). Ground truth for
doc05 (Creatinine, arrows) and doc06 (WBC, asterisk) both say `HH`. Whether the pipeline
recovers that turned out to hinge on two unrelated things, only one of which prompting
can fix:

- **doc05 (Creatinine, `↑↑`, inline_clean) — an OCR limitation, not a prompt problem.** A
  real Azure DI call on this document (`tests/python/test_di_client_integration.py`)
  shows DI itself reads the line as `"Creat: 1.6 mg/dL (Ref: 0.6-1.3) [11]"` — the doubled
  arrow is misread as the literal text `[11]`, and DI reports high confidence (0.973) for
  that wrong reading. The LLM never sees the real glyph, so no prompt wording can recover
  it. Confirmed it isn't "DI can't read arrows" generically: a **single** arrow isolated
  in its own table cell (doc02 Glucose, `rows`/`arrows`) reads perfectly (`"↑"`,
  confidence 1.0). It's specifically the doubled glyph crammed into dense inline free
  text, with no cell boundary to anchor it, that breaks DI.
- **doc06 (WBC, `**`, inline_clean) — a real prompt-engineering fix.** `**` is plain
  ASCII, so DI reads it correctly; the miss was the LLM mapping it to `H` instead of `HH`
  because nothing in the original prompt said a doubled symbol means "critical." Adding
  that one rule (`schema_annotated`/`few_shot`) fixes it, confirmed below.

`validate.py`'s plausibility check (recompute the flag from value vs. reference range; a
mismatch forces `needs_review`) still catches the doc05 miss downstream even though the
prompt can't — the value/range recompute doesn't care what glyph DI thought it saw. Real
evidence for the hybrid OCR+LLM trade-off and confidence/human-in-the-loop story: a wrong
high-confidence OCR read still gets caught by a domain-specific validation layer, not by
picking a marginally better prompt.

### A note on run-to-run variance

`gpt-5-mini` is a reasoning-class deployment and isn't called at `temperature=0` (Azure
restricts temperature control for reasoning models — see `llm_client.py`). Two anomalies
in an earlier sweep run (`schema_annotated` dropping all `ref_range_raw` values for one
document, and all `unit` values for another) turned out to be one-off sampling flakes,
not a prompt defect: three repeat calls against the identical cached layout and prompt
reproduced the correct fields every time. The tables below reflect the corrected,
non-flaky results.

### Results

**`terse`** ([full table](../eval/results_terse.md)):

| Field | inline_clean | Overall |
|---|---|---|
| printed_flag | 8/10 (80%) | 43/45 (96%) |
| *(all other fields)* | 100% | 100% |

**`schema_annotated`** ([full table](../eval/results_schema_annotated.md), matches the
production accuracy table above):

| Field | inline_clean | Overall |
|---|---|---|
| printed_flag | 9/10 (90%) | 44/45 (98%) |
| *(all other fields)* | 100% | 100% |

**`few_shot`** ([full table](../eval/results_few_shot.md)):

| Field | inline_clean | Overall |
|---|---|---|
| printed_flag | 9/10 (90%) | 44/45 (98%) |
| *(all other fields)* | 100% | 100% |

Every variant is at 100% on every field except `printed_flag`, and every variant's single
remaining `printed_flag` miss on `schema_annotated`/`few_shot` (and one of two on `terse`)
is doc05 — the OCR-limited case no prompt can fix. `terse`'s second miss is doc06, which
the doubled-flag rule fixes in the other two variants.

### Winner

`schema_annotated` and `few_shot` tie exactly (98% overall, doc05 is the only miss for
both). `terse` trails at 96% by missing the prompt-fixable doc06 case too, confirming the
doubled-flag rule is load-bearing, not cosmetic.

Given the tie, **`schema_annotated` wins**. With identical measured accuracy, `few_shot`'s
extra machinery isn't earning its keep:

- **Token cost, forever.** The worked example is a permanent per-request tax (latency + $)
  that bought zero accuracy improvement here.
- **Overfitting risk the project already flags.** A few-shot prompt can overfit the one
  template it saw. The eval corpus only has 6 layouts — not enough to reliably detect the
  model anchoring on the one example's surface formatting rather than the general rule.
  This pipeline's whole design premise is handling document variance *by construction*
  (DI + schema mapping), not by pattern-matching examples, so that risk isn't one to
  accept without evidence it pays for itself.
- **Maintenance burden.** The example has to stay in sync with the rules — if a field
  rule changes later, the worked example can silently start contradicting it.

`schema_annotated` is already `DEFAULT_PROMPT_VARIANT` in `llm_client.py`, so the winner
is already wired in; no code change was needed.

## Limitations

This eval is sized to distinguish prompt variants and catch regressions during
development, not to certify production accuracy. Worth stating plainly:

- **n is small.** 9 documents across 6 layouts means several per-layout cells are a single
  document (1/1 = 100%), and even the largest cells are 12 result rows. A single miss
  swings a cell from 100% to 0%, and a single hit swings it the other way — the headline
  percentages are far less statistically stable than the tidy table makes them look.
- **All documents are synthetic.** `sample_data/generate.py` produces clean, programmatically
  authored layouts. Real-world lab reports carry noise this corpus doesn't model: multi-page
  reports, mixed fonts, low-quality faxes/photos, handwritten annotations, lab-specific
  templates never seen here, and OCR failure modes beyond the one doubled-glyph case found
  in doc05.
- **Ground truth is authored, not independently adjudicated.** Because `generate.py` emits
  the PDF and its ground truth from the same source values, there's no inter-rater step and
  no chance of ground truth itself being ambiguous or wrong — which is convenient for this
  eval but doesn't test whether the schema/tolerance rules agree with a human reviewer on
  a real, messier document.
- **Layout coverage is intentionally narrow.** Six layouts were chosen to vary specific axes
  (table structure, flag notation, scan quality) for controlled comparison, not to sample
  the diversity of formats real labs use.

A production-scale eval would need on the order of tens of documents per layout (enough
for a miss to move a percentage by a few points, not fifty), a corpus of real de-identified
reports across multiple labs and scan qualities, and ground truth independently adjudicated
by a second rater to catch cases where the "correct" answer is itself debatable. None of
that invalidates the comparisons above — the harness and methodology carry over unchanged —
but the current n is right-sized for picking a prompt variant during development, not for
claiming a production accuracy number.