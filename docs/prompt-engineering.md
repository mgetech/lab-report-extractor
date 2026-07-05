# Prompt Engineering: Variant Comparison

Three system-prompt variants for `llm_client.py`'s structuring call were run across all 9
sample documents (6 layouts) and scored with the same per-field, per-layout harness used in
[`eval/results.md`](../eval/results.md). Reproduction: `eval/run_prompt_sweep.py`.

## Variants

| Variant | Description |
|---|---|
| `terse` | One short paragraph: map fields onto the schema, blank flag = normal, dates to ISO 8601. No per-field rules. |
| `schema_annotated` | Field-by-field rules (current production default) -- how to read `analyte`/`value`/`ref_range_raw`, the blank-flag-means-normal rule, date conversion, and a rule for doubled/repeated flag glyphs (`**` / `↑↑` / `↓↓`) meaning the *critical* variant (HH/LL), not a second plain flag. |
| `few_shot` | `schema_annotated` plus one worked example demonstrating a blank flag, a plain flag, and a doubled flag glyph together. |

`di_client.py`'s output doesn't depend on the LLM prompt, so the sweep runs Document
Intelligence once per document and reuses the layout across all three variants -- only the
LLM call varies.

## Why a doubled-flag rule exists at all

`sample_data/generate.py` renders a *critical* result as a doubled glyph for non-letter flag
styles -- `↑↑`/`↓↓` for arrows, `**` for asterisk (a plain `H`/`L` is a single glyph; `HH`/`LL`
critical results double it, matching real report conventions). Ground truth for doc05
(Creatinine, arrows) and doc06 (WBC, asterisk) both say `HH`. Whether the pipeline recovers
that turned out to hinge on two unrelated things, only one of which prompting can fix:

- **doc05 (Creatinine, `↑↑`, inline_clean) -- an OCR limitation, not a prompt problem.** A
  real Azure DI call on this document (`tests/python/test_di_client_integration.py`) shows DI
  itself reads the line as `"Creat: 1.6 mg/dL (Ref: 0.6-1.3) [11]"` -- the doubled arrow is
  misread as the literal text `[11]`, and DI reports high confidence (0.973) for that wrong
  reading. The LLM never sees the real glyph, so no prompt wording can recover it. Confirmed
  it isn't "DI can't read arrows" generically: a **single** arrow isolated in its own table
  cell (doc02 Glucose, `rows`/`arrows`) reads perfectly (`"↑"`, confidence 1.0). It's
  specifically the doubled glyph crammed into dense inline free text, with no cell boundary to
  anchor it, that breaks DI.
- **doc06 (WBC, `**`, inline_clean) -- a real prompt-engineering fix.** `**` is plain ASCII, so
  DI reads it correctly; the miss was the LLM mapping it to `H` instead of `HH` because
  nothing in the original prompt said a doubled symbol means "critical." Adding that one rule
  (`schema_annotated`/`few_shot`) fixes it, confirmed below.

`validate.py`'s plausibility check (recompute the flag from value vs. reference range; a
mismatch forces `needs_review`) still catches the doc05 miss downstream even though the
prompt can't -- the value/range recompute doesn't care what glyph DI thought it saw. Real
evidence for the hybrid OCR+LLM trade-off and confidence/human-in-the-loop story: a wrong
high-confidence OCR read still gets caught by a domain-specific validation layer, not by
picking a marginally better prompt.

## A note on run-to-run variance

`gpt-5-mini` is a reasoning-class deployment and isn't called at `temperature=0` (Azure
restricts temperature control for reasoning models -- see `llm_client.py`). Two anomalies in
an earlier sweep run (`schema_annotated` dropping all `ref_range_raw` values for one document,
and all `unit` values for another) turned out to be one-off sampling flakes, not a prompt
defect: three repeat calls against the identical cached layout and prompt reproduced the
correct fields every time. The tables below reflect the corrected, non-flaky results.

## Results

**`terse`** ([full table](../eval/results_terse.md)):

| Field | inline_clean | Overall |
|---|---|---|
| printed_flag | 8/10 (80%) | 43/45 (96%) |
| *(all other fields)* | 100% | 100% |

**`schema_annotated`** ([full table](../eval/results_schema_annotated.md), matches production
default -- see [`eval/results.md`](../eval/results.md)):

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
remaining `printed_flag` miss on `schema_annotated`/`few_shot` (and one of two on `terse`) is
doc05 -- the OCR-limited case no prompt can fix. `terse`'s second miss is doc06, which the
doubled-flag rule fixes in the other two variants.

## Winner

`schema_annotated` and `few_shot` tie exactly (98% overall, doc05 is the only miss for both).
`terse` trails at 96% by missing the prompt-fixable doc06 case too, confirming the doubled-flag
rule is load-bearing, not cosmetic.

Given the tie, **`schema_annotated` wins**. With identical measured accuracy, `few_shot`'s
extra machinery isn't earning its keep:

- **Token cost, forever.** The worked example is a permanent per-request tax (latency + $)
  that bought zero accuracy improvement here.
- **Overfitting risk the project already flags.** `CLAUDE.md` calls out that "a few-shot
  prompt can overfit the one template it saw." The eval corpus only has 6 layouts -- not
  enough to reliably detect the model anchoring on the one example's surface formatting rather
  than the general rule. This pipeline's whole design premise is handling document variance
  *by construction* (DI + schema mapping), not by pattern-matching examples, so that risk
  isn't one to accept without evidence it pays for itself.
- **Maintenance burden.** The example has to stay in sync with the rules -- if a field rule
  changes later, the worked example can silently start contradicting it.

`schema_annotated` is already `DEFAULT_PROMPT_VARIANT` in `llm_client.py`, so the winner is
already wired in; no code change was needed.