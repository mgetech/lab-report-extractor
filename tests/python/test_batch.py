from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from batch import find_documents, process_document, run_batch
from di_client import DocumentIntelligenceError
from llm_client import LLMExtractionError
from schema import Flag, LabReport, Patient, Result


def _report(source_file: str, needs_review: bool = False) -> LabReport:
    return LabReport(
        source_file=source_file,
        extraction_model="gpt-5-mini",
        extracted_at=datetime(2026, 7, 4, 9, 0, 0),
        report_date=date(2026, 6, 20),
        patient=Patient(patient_id="P-1001", name="Jordan Ellery Voss"),
        results=[
            Result(
                analyte="Hgb",
                value="14.2",
                unit="g/dL",
                ref_range_raw="13.5-17.5",
                printed_flag=Flag.NORMAL,
                confidence=0.9 if not needs_review else 0.2,
            )
        ],
    )


# --- find_documents ----------------------------------------------------


def test_find_documents_filters_by_extension_and_sorts(tmp_path):
    (tmp_path / "b.pdf").write_bytes(b"%PDF")
    (tmp_path / "a.PNG").write_bytes(b"fake-png")
    (tmp_path / "notes.txt").write_text("ignore me")

    docs = find_documents(tmp_path)

    assert [p.name for p in docs] == ["a.PNG", "b.pdf"]


def test_find_documents_empty_dir(tmp_path):
    assert find_documents(tmp_path) == []


# --- process_document ----------------------------------------------------


def test_process_document_runs_full_pipeline(mocker, tmp_path):
    doc_path = tmp_path / "doc01.pdf"
    doc_path.write_bytes(b"%PDF-fake-bytes")

    fake_di = mocker.Mock()
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm = mocker.Mock()
    fake_llm.extract.return_value = _report("doc01.pdf")

    report = process_document(doc_path, fake_di, fake_llm)

    fake_di.analyze_layout.assert_called_once_with(b"%PDF-fake-bytes")
    fake_llm.extract.assert_called_once_with("fake-layout", source_file="doc01.pdf")
    # transform.py canonicalizes the "Hgb" synonym -- proves transform/validate ran.
    assert report.results[0].analyte == "Hemoglobin"
    assert report.results[0].computed_flag == Flag.NORMAL


def test_process_document_propagates_di_error(mocker, tmp_path):
    doc_path = tmp_path / "corrupt.pdf"
    doc_path.write_bytes(b"not-a-real-pdf")

    fake_di = mocker.Mock()
    fake_di.analyze_layout.side_effect = DocumentIntelligenceError("corrupt document")

    with pytest.raises(DocumentIntelligenceError):
        process_document(doc_path, fake_di, mocker.Mock())


def test_process_document_propagates_llm_error(mocker, tmp_path):
    doc_path = tmp_path / "doc01.pdf"
    doc_path.write_bytes(b"%PDF-fake-bytes")

    fake_di = mocker.Mock()
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm = mocker.Mock()
    fake_llm.extract.side_effect = LLMExtractionError("model unavailable")

    with pytest.raises(LLMExtractionError):
        process_document(doc_path, fake_di, fake_llm)


# --- run_batch --------------------------------------------------------------


def test_run_batch_empty_input_dir_prints_message_and_writes_nothing(tmp_path, capsys, mocker):
    output_dir = tmp_path / "out"
    run_batch(tmp_path, output_dir, mocker.Mock(), mocker.Mock())

    assert "No documents found" in capsys.readouterr().out
    assert not output_dir.exists()


def test_run_batch_processes_all_docs_writes_json_and_parquet_and_skips_failures(
    mocker, tmp_path
):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc01.pdf").write_bytes(b"%PDF-good")
    (input_dir / "doc02.pdf").write_bytes(b"%PDF-corrupt")
    output_dir = tmp_path / "out"

    fake_di = mocker.Mock()
    fake_di.analyze_layout.side_effect = [
        "fake-layout",
        DocumentIntelligenceError("corrupt document"),
    ]
    fake_llm = mocker.Mock()
    fake_llm.extract.return_value = _report("doc01.pdf")

    run_batch(input_dir, output_dir, fake_di, fake_llm)

    assert (output_dir / "doc01.json").exists()
    assert not (output_dir / "doc02.json").exists()

    error_log = (output_dir / "errors.log").read_text()
    assert "doc02.pdf" in error_log
    assert "corrupt document" in error_log

    table = pq.read_table(output_dir / "batch_results.parquet")
    rows = table.to_pylist()
    assert len(rows) == 1
    assert rows[0]["source_file"] == "doc01.pdf"
    assert rows[0]["analyte"] == "Hemoglobin"


def test_run_batch_writes_no_parquet_when_every_document_fails(mocker, tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc01.pdf").write_bytes(b"%PDF-corrupt")
    output_dir = tmp_path / "out"

    fake_di = mocker.Mock()
    fake_di.analyze_layout.side_effect = DocumentIntelligenceError("corrupt document")

    run_batch(input_dir, output_dir, fake_di, mocker.Mock())

    assert not (output_dir / "batch_results.parquet").exists()
    assert (output_dir / "errors.log").exists()


def test_run_batch_prints_progress_with_review_status(mocker, tmp_path, capsys):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "doc01.pdf").write_bytes(b"%PDF-good")
    output_dir = tmp_path / "out"

    fake_di = mocker.Mock()
    fake_di.analyze_layout.return_value = "fake-layout"
    fake_llm = mocker.Mock()
    fake_llm.extract.return_value = _report("doc01.pdf", needs_review=True)

    run_batch(input_dir, output_dir, fake_di, fake_llm)

    out = capsys.readouterr().out
    assert "[1/1] doc01.pdf" in out
    assert "OK (needs review)" in out
    assert "1 succeeded, 0 failed" in out