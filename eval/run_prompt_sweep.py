"""Run every prompt variant in `llm_client._SYSTEM_PROMPTS` over all sample documents and
score each against ground truth, to pick a winner for docs/prompt-engineering.md.

Document Intelligence is called once per document and the layout is reused across variants
(DI's output doesn't depend on the LLM prompt) -- this cuts DI calls from
variants * documents down to just documents, sparing the free-tier DI resource.

Usage (run with the extractor's venv):
    src/extractor/.venv/Scripts/python.exe eval/run_prompt_sweep.py

Writes per-variant extraction JSON to `output/sweep/<variant>/` and a per-variant results
table to `eval/results_<variant>.md`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src" / "extractor"))

from di_client import DIClient, DocumentIntelligenceError  # noqa: E402
from evaluate import evaluate, render_markdown  # noqa: E402
from llm_client import _SYSTEM_PROMPTS, LLMClient, LLMExtractionError  # noqa: E402
from transform import transform_report  # noqa: E402
from validate import validate_report  # noqa: E402

PDFS_DIR = _REPO_ROOT / "sample_data" / "pdfs"
GROUND_TRUTH_DIR = _REPO_ROOT / "sample_data" / "ground_truth"
OUTPUT_ROOT = _REPO_ROOT / "output" / "sweep"


def main() -> None:
    load_dotenv()
    di_client = DIClient(
        endpoint=os.environ["AZURE_DI_ENDPOINT"], api_key=os.environ["AZURE_DI_KEY"]
    )
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    llm_clients = {
        variant: LLMClient(
            endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            deployment=deployment,
            prompt_variant=variant,
        )
        for variant in _SYSTEM_PROMPTS
    }

    documents = sorted(PDFS_DIR.glob("*.pdf"))
    print(f"Sweeping {len(_SYSTEM_PROMPTS)} prompt variants over {len(documents)} documents...")

    for variant in _SYSTEM_PROMPTS:
        (OUTPUT_ROOT / variant).mkdir(parents=True, exist_ok=True)

    for i, path in enumerate(documents, start=1):
        print(f"[{i}/{len(documents)}] {path.name}")
        try:
            layout = di_client.analyze_layout(path.read_bytes())
        except DocumentIntelligenceError as exc:
            print(f"  DI FAILED: {exc}")
            continue

        for variant, llm_client in llm_clients.items():
            try:
                report = llm_client.extract(layout, source_file=path.name)
                report = validate_report(transform_report(report))
            except LLMExtractionError as exc:
                print(f"  [{variant}] LLM FAILED: {exc}")
                continue
            out_path = OUTPUT_ROOT / variant / f"{path.stem}.json"
            out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
            print(f"  [{variant}] OK{' (needs review)' if report.needs_review else ''}")

    print("\n--- Results ---")
    for variant in _SYSTEM_PROMPTS:
        stats, skipped = evaluate(OUTPUT_ROOT / variant, GROUND_TRUTH_DIR)
        table = render_markdown(stats)
        results_path = _REPO_ROOT / "eval" / f"results_{variant}.md"
        results_path.write_text(table + "\n", encoding="utf-8")
        print(f"\n### {variant} (-> {results_path.relative_to(_REPO_ROOT)})")
        print(table)
        if skipped:
            print(f"Skipped (DI/LLM failed): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
