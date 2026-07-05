from datetime import date
from types import SimpleNamespace

import pytest
from di_client import LayoutResult, Page, WordConfidence
from llm_client import (
    LLMClient,
    LLMExtractionError,
    _ExtractedDiagnosis,
    _ExtractedLabReport,
    _ExtractedResult,
)
from openai import APIConnectionError
from schema import Flag, Patient, Sex


def _layout() -> LayoutResult:
    page = Page(
        page_number=1,
        words=[
            WordConfidence(content="Hemoglobin", confidence=0.98),
            WordConfidence(content="14.2", confidence=0.55),
        ],
    )
    return LayoutResult(content="Hemoglobin 14.2", pages=[page])


def _extracted() -> _ExtractedLabReport:
    return _ExtractedLabReport(
        report_date=date(2026, 6, 20),
        collection_date=date(2026, 6, 19),
        ordering_physician="Dr. Priya Anand",
        lab_name="Meridian Health Labs",
        patient=Patient(
            patient_id="P-1001", name="Jordan Ellery Voss", dob=date(1985, 3, 14), sex=Sex.FEMALE
        ),
        results=[
            _ExtractedResult(
                analyte="Hemoglobin",
                value="14.2",
                unit="g/dL",
                ref_range_raw="13.5-17.5",
                printed_flag=Flag.NORMAL,
            )
        ],
        diagnoses=[_ExtractedDiagnosis(text="Routine checkup - no abnormalities")],
    )


def _client_with_stub_parse(mocker, parsed=None, refusal=None, parse_error=None):
    stub_sdk_client = mocker.Mock()
    if parse_error is not None:
        stub_sdk_client.chat.completions.parse.side_effect = parse_error
    else:
        message = SimpleNamespace(parsed=parsed, refusal=refusal)
        stub_sdk_client.chat.completions.parse.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=message)]
        )
    mocker.patch("llm_client.OpenAI", return_value=stub_sdk_client)
    client = LLMClient(
        endpoint="https://example.openai.azure.com/openai/v1",
        api_key="fake-key",
        deployment="gpt-5-mini",
    )
    return client, stub_sdk_client


def test_extract_maps_llm_output_onto_lab_report(mocker):
    client, _ = _client_with_stub_parse(mocker, parsed=_extracted())

    report = client.extract(_layout(), source_file="doc01.pdf")

    assert report.source_file == "doc01.pdf"
    assert report.extraction_model == "gpt-5-mini"
    assert report.patient.name == "Jordan Ellery Voss"
    assert report.report_date == date(2026, 6, 20)
    assert len(report.results) == 1
    assert report.results[0].analyte == "Hemoglobin"
    assert report.results[0].printed_flag == Flag.NORMAL
    assert report.results[0].ref_low is None  # left for transform.py (Day 2)
    assert report.needs_review is False


def test_extract_computes_confidence_from_matching_di_word(mocker):
    client, _ = _client_with_stub_parse(mocker, parsed=_extracted())

    report = client.extract(_layout(), source_file="doc01.pdf")

    assert report.results[0].confidence == pytest.approx(0.55)


def test_extract_falls_back_to_document_mean_confidence_when_no_word_matches(mocker):
    extracted = _extracted()
    extracted.results[0].value = "999.9"  # no matching DI word
    client, _ = _client_with_stub_parse(mocker, parsed=extracted)

    report = client.extract(_layout(), source_file="doc01.pdf")

    assert report.results[0].confidence == pytest.approx((0.98 + 0.55) / 2)


def test_extract_computes_diagnosis_confidence_as_document_mean(mocker):
    client, _ = _client_with_stub_parse(mocker, parsed=_extracted())

    report = client.extract(_layout(), source_file="doc01.pdf")

    assert report.diagnoses[0].confidence == pytest.approx((0.98 + 0.55) / 2)


def test_extract_raises_on_openai_error(mocker):
    error = APIConnectionError(request=mocker.Mock())
    client, _ = _client_with_stub_parse(mocker, parse_error=error)

    with pytest.raises(LLMExtractionError):
        client.extract(_layout(), source_file="doc01.pdf")


def test_extract_raises_when_model_returns_no_parsed_content(mocker):
    client, _ = _client_with_stub_parse(mocker, parsed=None, refusal="cannot process request")

    with pytest.raises(LLMExtractionError):
        client.extract(_layout(), source_file="doc01.pdf")


def test_ping_succeeds_when_models_list_reachable(mocker):
    client, stub_sdk_client = _client_with_stub_parse(mocker)

    client.ping()

    stub_sdk_client.models.list.assert_called_once()


def test_ping_raises_llm_extraction_error_on_failure(mocker):
    client, stub_sdk_client = _client_with_stub_parse(mocker)
    stub_sdk_client.models.list.side_effect = APIConnectionError(request=mocker.Mock())

    with pytest.raises(LLMExtractionError):
        client.ping()


def test_extract_sends_deployment_and_document_content_to_sdk(mocker):
    client, stub_sdk_client = _client_with_stub_parse(mocker, parsed=_extracted())

    client.extract(_layout(), source_file="doc01.pdf")

    _, kwargs = stub_sdk_client.chat.completions.parse.call_args
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["response_format"] is _ExtractedLabReport
    assert "Hemoglobin 14.2" in kwargs["messages"][1]["content"]


def test_default_prompt_variant_is_schema_annotated(mocker):
    client, stub_sdk_client = _client_with_stub_parse(mocker, parsed=_extracted())

    client.extract(_layout(), source_file="doc01.pdf")

    _, kwargs = stub_sdk_client.chat.completions.parse.call_args
    assert "Rules:" in kwargs["messages"][0]["content"]


def test_terse_prompt_variant_sends_the_terse_system_prompt(mocker):
    stub_sdk_client = mocker.Mock()
    message = SimpleNamespace(parsed=_extracted(), refusal=None)
    stub_sdk_client.chat.completions.parse.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=message)]
    )
    mocker.patch("llm_client.OpenAI", return_value=stub_sdk_client)
    client = LLMClient(
        endpoint="https://example.openai.azure.com/openai/v1",
        api_key="fake-key",
        deployment="gpt-5-mini",
        prompt_variant="terse",
    )

    client.extract(_layout(), source_file="doc01.pdf")

    _, kwargs = stub_sdk_client.chat.completions.parse.call_args
    assert "Rules:" not in kwargs["messages"][0]["content"]


def test_unknown_prompt_variant_raises_value_error():
    with pytest.raises(ValueError, match="Unknown prompt_variant"):
        LLMClient(
            endpoint="https://example.openai.azure.com/openai/v1",
            api_key="fake-key",
            deployment="gpt-5-mini",
            prompt_variant="bogus",
        )