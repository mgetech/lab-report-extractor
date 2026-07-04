"""Real-Azure smoke test for di_client.py. Hits live Document Intelligence — run locally
only with a populated .env (`pytest -m integration`); excluded from CI by default addopts.
"""

import dataclasses
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from di_client import DIClient

load_dotenv()

SAMPLE_PDF = Path(__file__).parent / "../../sample_data/pdfs/doc01_rows_clean.pdf"


@pytest.mark.integration
def test_analyze_layout_against_real_document_intelligence():
    endpoint = os.environ.get("AZURE_DI_ENDPOINT")
    api_key = os.environ.get("AZURE_DI_KEY")
    if not endpoint or not api_key:
        pytest.skip("AZURE_DI_ENDPOINT / AZURE_DI_KEY not set in .env")

    client = DIClient(endpoint=endpoint, api_key=api_key)
    result = client.analyze_layout(SAMPLE_PDF.read_bytes())

    # print(json.dumps(dataclasses.asdict(result), indent=2))

    assert result.content.strip()
    assert result.pages
    assert result.tables
    assert any(word.confidence > 0 for page in result.pages for word in page.words)


@pytest.mark.integration
def test_ping_against_real_document_intelligence():
    endpoint = os.environ.get("AZURE_DI_ENDPOINT")
    api_key = os.environ.get("AZURE_DI_KEY")
    if not endpoint or not api_key:
        pytest.skip("AZURE_DI_ENDPOINT / AZURE_DI_KEY not set in .env")

    DIClient(endpoint=endpoint, api_key=api_key).ping()  # raises on failure
