import json
from datetime import date, datetime

import pytest
from di_client import DocumentIntelligenceError
from fastapi.testclient import TestClient
from llm_client import LLMExtractionError
from schema import Flag, LabReport, Patient, Result

import main
from main import app, get_di_client, get_llm_client


def _sample_report() -> LabReport:
    return LabReport(
        source_file="doc.pdf",
        extraction_model="gpt-5-mini",
        extracted_at=datetime(2026, 7, 4, 9, 0, 0),
        report_date=date(2026, 6, 20),
        patient=Patient(patient_id="P-1001", name="Jordan Ellery Voss"),
        results=[
            Result(analyte="Hemoglobin", value="14.2", confidence=0.98, printed_flag=Flag.NORMAL)
        ],
    )


@pytest.fixture
def client(mocker, tmp_path):
    fake_di = mocker.Mock()
    fake_llm = mocker.Mock()
    mocker.patch.object(main, "OUTPUT_DIR", tmp_path)
    app.dependency_overrides[get_di_client] = lambda: fake_di
    app.dependency_overrides[get_llm_client] = lambda: fake_llm
    yield TestClient(app), fake_di, fake_llm
    app.dependency_overrides.clear()


def test_health_returns_ok(client):
    test_client, _, _ = client

    response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_returns_structured_report(client):
    test_client, fake_di, fake_llm = client
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm.extract.return_value = _sample_report()

    response = test_client.post(
        "/extract", files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_file"] == "doc.pdf"
    assert body["results"][0]["analyte"] == "Hemoglobin"
    fake_di.analyze_layout.assert_called_once_with(b"%PDF-fake-bytes")
    fake_llm.extract.assert_called_once_with("fake-layout", source_file="doc.pdf")


def test_extract_persists_result_as_json_file(client):
    test_client, fake_di, fake_llm = client
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm.extract.return_value = _sample_report()

    test_client.post(
        "/extract", files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")}
    )

    out_path = main.OUTPUT_DIR / "doc.json"
    assert out_path.exists()
    assert json.loads(out_path.read_text())["source_file"] == "doc.pdf"


def test_extract_returns_422_on_unreadable_document(client):
    test_client, fake_di, _ = client
    fake_di.analyze_layout.side_effect = DocumentIntelligenceError("corrupt document")

    response = test_client.post(
        "/extract", files={"file": ("bad.pdf", b"not-a-pdf", "application/pdf")}
    )

    assert response.status_code == 422


def test_extract_returns_502_on_llm_failure(client):
    test_client, fake_di, fake_llm = client
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm.extract.side_effect = LLMExtractionError("model unavailable")

    response = test_client.post(
        "/extract", files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")}
    )

    assert response.status_code == 502