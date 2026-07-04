"""Batch CLI: run the extraction pipeline (DI -> LLM -> transform -> validate) over every
document in a folder.

Usage:
    python batch.py <input_dir> [--output-dir DIR]

Writes one JSON file per document (same shape `main.py` persists) plus a single
`batch_results.parquet` -- one row per result, flattened with its parent report's
fields -- for downstream eval/analytics. A corrupt/unreadable document or an LLM failure
is logged to `errors.log` in the output directory and the batch moves on to the next
document; one bad file never aborts the run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv

from di_client import DIClient, DocumentIntelligenceError
from llm_client import LLMClient, LLMExtractionError
from schema import LabReport, Result
from transform import transform_report
from validate import validate_report

logger = logging.getLogger(__name__)

_DOCUMENT_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff")


def find_documents(input_dir: Path) -> list[Path]:
    """Every supported document in `input_dir`, sorted for a stable/reproducible run order."""
    return sorted(p for p in input_dir.iterdir() if p.suffix.lower() in _DOCUMENT_EXTENSIONS)


def process_document(path: Path, di_client: DIClient, llm_client: LLMClient) -> LabReport:
    """Run one document through DI -> LLM -> transform -> validate.

    Raises `DocumentIntelligenceError`/`LLMExtractionError` on failure -- `run_batch`
    catches these to log, skip, and continue rather than let one bad document abort
    the batch.
    """
    document_bytes = path.read_bytes()
    layout = di_client.analyze_layout(document_bytes)
    report = llm_client.extract(layout, source_file=path.name)
    return validate_report(transform_report(report))


def _flatten_result(report: LabReport, result: Result) -> dict[str, Any]:
    """One Parquet row: a result's fields flattened with its parent report's fields."""
    return {
        "source_file": report.source_file,
        "extraction_model": report.extraction_model,
        "extracted_at": report.extracted_at.isoformat(),
        "report_date": report.report_date.isoformat() if report.report_date else None,
        "collection_date": report.collection_date.isoformat() if report.collection_date else None,
        "ordering_physician": report.ordering_physician,
        "lab_name": report.lab_name,
        "report_needs_review": report.needs_review,
        "patient_id": report.patient.patient_id,
        "patient_name": report.patient.name,
        "analyte": result.analyte,
        "value": result.value,
        "unit": result.unit,
        "ref_range_raw": result.ref_range_raw,
        "ref_low": result.ref_low,
        "ref_high": result.ref_high,
        "printed_flag": result.printed_flag.value if result.printed_flag else None,
        "computed_flag": result.computed_flag.value if result.computed_flag else None,
        "confidence": result.confidence,
        "result_needs_review": result.needs_review,
    }


def _persist_json(report: LabReport, output_dir: Path) -> Path:
    out_path = output_dir / f"{Path(report.source_file).stem}.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return out_path


def run_batch(
    input_dir: Path, output_dir: Path, di_client: DIClient, llm_client: LLMClient
) -> None:
    """Process every document in `input_dir`, printing per-document progress.

    Writes per-document JSON and a combined `batch_results.parquet` to `output_dir`, plus
    an `errors.log` recording any document that failed DI or LLM extraction.
    """
    documents = find_documents(input_dir)
    if not documents:
        print(f"No documents found in {input_dir}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    error_log_path = output_dir / "errors.log"
    rows: list[dict[str, Any]] = []
    error_count = 0

    with error_log_path.open("w", encoding="utf-8") as error_log:
        for i, path in enumerate(documents, start=1):
            print(f"[{i}/{len(documents)}] {path.name} ... ", end="", flush=True)
            try:
                report = process_document(path, di_client, llm_client)
            except (DocumentIntelligenceError, LLMExtractionError) as exc:
                print("FAILED")
                logger.error("Failed to process %s: %s", path.name, exc)
                error_log.write(f"{path.name}: {exc}\n")
                error_count += 1
                continue

            _persist_json(report, output_dir)
            rows.extend(_flatten_result(report, result) for result in report.results)
            print("OK (needs review)" if report.needs_review else "OK")

    if rows:
        pq.write_table(pa.Table.from_pylist(rows), output_dir / "batch_results.parquet")

    succeeded = len(documents) - error_count
    print(f"\nProcessed {len(documents)} document(s): {succeeded} succeeded, {error_count} failed.")
    if error_count:
        print(f"See {error_log_path} for details.")


def _build_clients() -> tuple[DIClient, LLMClient]:
    di_client = DIClient(
        endpoint=os.environ["AZURE_DI_ENDPOINT"], api_key=os.environ["AZURE_DI_KEY"]
    )
    llm_client = LLMClient(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    )
    return di_client, llm_client


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Batch-run the extraction pipeline over a folder of lab reports."
    )
    parser.add_argument("input_dir", type=Path, help="Folder of lab report PDFs/images.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/batch"),
        help="Folder to write per-doc JSON + batch_results.parquet (default: output/batch).",
    )
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Not a directory: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    di_client, llm_client = _build_clients()
    run_batch(args.input_dir, args.output_dir, di_client, llm_client)


if __name__ == "__main__":
    main()
