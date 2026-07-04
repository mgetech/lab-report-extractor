"""Real-Azure smoke test for llm_client.py. Hits live Document Intelligence *and*
Azure OpenAI (Foundry deployment) -- run locally only with a populated .env
(`pytest -m integration`); excluded from CI by default addopts.
"""

import os
from pathlib import Path

import pytest
from di_client import DIClient
from dotenv import load_dotenv
from llm_client import LLMClient
from schema import Flag

load_dotenv()

SAMPLE_PDF = Path(__file__).parent / "../../sample_data/pdfs/doc01_rows_clean.pdf"


@pytest.mark.integration
def test_extract_against_real_document_intelligence_and_azure_openai():
    di_endpoint = os.environ.get("AZURE_DI_ENDPOINT")
    di_key = os.environ.get("AZURE_DI_KEY")
    llm_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    llm_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not all([di_endpoint, di_key, llm_endpoint, llm_key, deployment]):
        pytest.skip("AZURE_DI_* / AZURE_OPENAI_* not set in .env")

    layout = DIClient(endpoint=di_endpoint, api_key=di_key).analyze_layout(SAMPLE_PDF.read_bytes())
    client = LLMClient(endpoint=llm_endpoint, api_key=llm_key, deployment=deployment)

    report = client.extract(layout, source_file=SAMPLE_PDF.name)

    print(report.model_dump_json(indent=2))

    assert report.source_file == SAMPLE_PDF.name
    assert report.extraction_model == deployment
    assert report.patient.name
    assert report.results
    assert all(0.0 <= r.confidence <= 1.0 for r in report.results)
    # doc01 prints Hemoglobin as the flagged (low) result -- a real signal the model
    # read the printed flag rather than defaulting everything to normal.
    assert any(r.printed_flag == Flag.LOW for r in report.results)


@pytest.mark.integration
def test_ping_against_real_azure_openai():
    llm_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    llm_key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not all([llm_endpoint, llm_key, deployment]):
        pytest.skip("AZURE_OPENAI_* not set in .env")

    LLMClient(endpoint=llm_endpoint, api_key=llm_key, deployment=deployment).ping()