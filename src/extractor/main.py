"""Python extraction engine (FastAPI): `POST /extract` structures one document into a
validated `LabReport`; `GET /health` reports process liveness.

Stateless -- never writes to Postgres. Azure DI/OpenAI clients are built once from env
vars and injected via FastAPI dependencies, so tests can override them with mocks
instead of hitting real Azure services.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, UploadFile

from di_client import DIClient, DocumentIntelligenceError
from llm_client import LLMClient, LLMExtractionError
from schema import LabReport
from transform import transform_report
from validate import validate_report

load_dotenv()

logger = logging.getLogger(__name__)

app = FastAPI(title="Lab Report Extractor")

# Python is stateless and never writes to Postgres
# but it does write its structured JSON output to disk for eval purposes.
_REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(os.environ.get("EXTRACTOR_OUTPUT_DIR", _REPO_ROOT / "output"))


def _persist_report(report: LabReport) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{Path(report.source_file).stem}.json"
    out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return out_path


@lru_cache
def get_di_client() -> DIClient:
    return DIClient(endpoint=os.environ["AZURE_DI_ENDPOINT"], api_key=os.environ["AZURE_DI_KEY"])


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient(
        endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Process liveness only, no external calls -- safe for the Docker smoke test to hit
    without live Azure keys."""
    return {"status": "ok"}


@app.get("/ready")
def ready(
    di_client: DIClient = Depends(get_di_client),
    llm_client: LLMClient = Depends(get_llm_client),
) -> dict[str, str]:
    """Azure DI + Azure OpenAI reachability, in addition to `/health`'s process liveness."""
    try:
        di_client.ping()
    except DocumentIntelligenceError as exc:
        raise HTTPException(
            status_code=503, detail=f"Document Intelligence unreachable: {exc}"
        ) from exc

    try:
        llm_client.ping()
    except LLMExtractionError as exc:
        raise HTTPException(status_code=503, detail=f"Azure OpenAI unreachable: {exc}") from exc

    return {"status": "ready"}


@app.post("/extract", response_model=LabReport)
async def extract(
    file: UploadFile,
    di_client: DIClient = Depends(get_di_client),
    llm_client: LLMClient = Depends(get_llm_client),
) -> LabReport:
    """Document upload -> Azure DI layout -> Azure OpenAI structuring -> transform ->
    validate -> validated `LabReport`."""
    document_bytes = await file.read()

    try:
        layout = di_client.analyze_layout(document_bytes)
    except DocumentIntelligenceError as exc:
        logger.error("DI analysis failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        report = llm_client.extract(layout, source_file=file.filename or "unknown")
    except LLMExtractionError as exc:
        logger.error("LLM extraction failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    report = validate_report(transform_report(report))

    out_path = _persist_report(report)
    logger.info("Persisted extraction result to %s", out_path)
    return report
