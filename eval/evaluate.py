"""Per-field, per-layout accuracy of extracted lab reports against ground truth.

Compares each extracted `LabReport` JSON (produced by `batch.py` or persisted by
`main.py`'s `/extract`) to its matching file in `sample_data/ground_truth/`. Report
fields are compared directly; result rows are paired by canonicalized analyte name
(via `transform.canonicalize_analyte`) since row order/count can differ between the
extraction and the ground truth.

Accuracy is broken down by layout -- the doc_id suffix after the `docNN_` prefix (e.g.
`rows_clean`, `panels_scanned`, `rows_adversarial`) -- so the "handles document
variance" requirement is shown, not claimed.

Usage (run with the extractor's venv, since `schema.py`/`transform.py` are installed
editable there and not on a plain interpreter's path):
    src/extractor/.venv/Scripts/python.exe eval/evaluate.py \\
        [--extracted-dir output/batch] [--ground-truth-dir sample_data/ground_truth] \\
        [--output eval/results.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src" / "extractor"))

from schema import LabReport, Result  # noqa: E402
from transform import canonicalize_analyte, parse_numeric  # noqa: E402

REPORT_FIELDS = [
    "report_date",
    "collection_date",
    "ordering_physician",
    "lab_name",
    "patient.patient_id",
    "patient.name",
    "patient.dob",
    "patient.sex",
]
RESULT_FIELDS = ["value", "unit", "ref_low", "ref_high", "printed_flag"]
ALL_FIELDS = [*REPORT_FIELDS, *RESULT_FIELDS, "result_recall"]

# layout -> field -> [correct, total]
Stats = dict[str, dict[str, list[int]]]


def _get(obj: Any, dotted_path: str) -> Any:
    for part in dotted_path.split("."):
        obj = getattr(obj, part)
    return obj


def _values_equal(field: str, expected: Any, actual: Any) -> bool:
    """Field-aware equality: numeric-with-tolerance for value/ref_low/ref_high (values
    are compared as numbers so printed-format differences like "0.90" vs "0.9" don't
    count as mismatches), case/whitespace-insensitive for text, exact otherwise."""
    if field in ("value", "ref_low", "ref_high"):
        expected_num = parse_numeric(expected) if isinstance(expected, str) else expected
        actual_num = parse_numeric(actual) if isinstance(actual, str) else actual
        if expected_num is None and actual_num is None:
            return True
        if expected_num is None or actual_num is None:
            return False
        return abs(expected_num - actual_num) <= 1e-6
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().casefold() == actual.strip().casefold()
    return expected == actual


def _layout_key(stem: str) -> str:
    """Layout label for a doc_id like `doc01_rows_clean` -> `rows_clean`."""
    prefix, _, rest = stem.partition("_")
    return rest if prefix.startswith("doc") and rest else stem


def _match_results(
    expected: list[Result], actual: list[Result]
) -> tuple[list[tuple[Result, Result]], list[Result], list[Result]]:
    """Pair ground-truth and extracted results by canonicalized analyte name.

    Returns (matched pairs, ground-truth rows never found in the extraction, extracted
    rows that don't correspond to any ground-truth row).
    """
    by_analyte = {canonicalize_analyte(r.analyte): r for r in actual}
    matched: list[tuple[Result, Result]] = []
    missing: list[Result] = []
    for gt_result in expected:
        found = by_analyte.pop(canonicalize_analyte(gt_result.analyte), None)
        (matched.append((gt_result, found)) if found else missing.append(gt_result))
    return matched, missing, list(by_analyte.values())


def _record(stats: Stats, layout: str, field: str, correct: bool) -> None:
    for key in (layout, "Overall"):
        bucket = stats.setdefault(key, {}).setdefault(field, [0, 0])
        bucket[0] += int(correct)
        bucket[1] += 1


def _score_document(expected: LabReport, actual: LabReport, stats: Stats) -> None:
    layout = _layout_key(Path(expected.source_file).stem)
    for field in REPORT_FIELDS:
        expected_value = _get(expected, field)
        actual_value = _get(actual, field)
        _record(stats, layout, field, _values_equal(field, expected_value, actual_value))

    matched, missing, _extra = _match_results(expected.results, actual.results)
    for gt_result, pred_result in matched:
        _record(stats, layout, "result_recall", True)
        for field in RESULT_FIELDS:
            expected_value = getattr(gt_result, field)
            actual_value = getattr(pred_result, field)
            _record(stats, layout, field, _values_equal(field, expected_value, actual_value))
    for _ in missing:
        _record(stats, layout, "result_recall", False)
        for field in RESULT_FIELDS:
            _record(stats, layout, field, False)


def evaluate(extracted_dir: Path, ground_truth_dir: Path) -> tuple[Stats, list[str]]:
    """Score every ground-truth document with a matching extraction in `extracted_dir`.

    Returns the accuracy stats and the list of ground-truth stems with no matching
    extraction file (skipped, not counted as a failure -- that document simply hasn't
    been run through the pipeline yet).
    """
    stats: Stats = {}
    skipped: list[str] = []
    for gt_path in sorted(ground_truth_dir.glob("*.json")):
        extracted_path = extracted_dir / gt_path.name
        if not extracted_path.is_file():
            skipped.append(gt_path.stem)
            continue
        expected = LabReport.model_validate_json(gt_path.read_text(encoding="utf-8"))
        actual = LabReport.model_validate_json(extracted_path.read_text(encoding="utf-8"))
        _score_document(expected, actual, stats)
    return stats, skipped


def render_markdown(stats: Stats) -> str:
    """Field x layout accuracy table, with an `Overall` column, as GitHub-flavored
    markdown."""
    layouts = sorted(key for key in stats if key != "Overall")
    columns = [*layouts, "Overall"]
    lines = [
        "| Field | " + " | ".join(columns) + " |",
        "|" + "---|" * (len(columns) + 1),
    ]
    for field in ALL_FIELDS:
        cells = []
        for column in columns:
            correct, total = stats.get(column, {}).get(field, [0, 0])
            cells.append(f"{correct}/{total} ({correct / total:.0%})" if total else "-")
        lines.append(f"| {field} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-field, per-layout accuracy of extracted lab reports vs ground truth."
    )
    parser.add_argument(
        "--extracted-dir",
        type=Path,
        default=_REPO_ROOT / "output" / "batch",
        help="Folder of extracted LabReport JSON (default: output/batch, batch.py's default).",
    )
    parser.add_argument(
        "--ground-truth-dir",
        type=Path,
        default=_REPO_ROOT / "sample_data" / "ground_truth",
        help="Folder of ground-truth LabReport JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "results.md",
        help="Where to write the markdown results table.",
    )
    args = parser.parse_args()

    stats, skipped = evaluate(args.extracted_dir, args.ground_truth_dir)
    if not stats:
        print(f"No matching extractions found in {args.extracted_dir}", file=sys.stderr)
        sys.exit(1)

    table = render_markdown(stats)
    args.output.write_text(table + "\n", encoding="utf-8")
    print(table)
    if skipped:
        print(f"\nSkipped (no extraction found): {', '.join(skipped)}", file=sys.stderr)


if __name__ == "__main__":
    main()
