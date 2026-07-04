from types import SimpleNamespace

import pytest
from azure.core.exceptions import HttpResponseError
from di_client import DIClient, DocumentIntelligenceError


def _span(offset: int, length: int) -> SimpleNamespace:
    return SimpleNamespace(offset=offset, length=length)


def _word(content: str, offset: int, confidence: float) -> SimpleNamespace:
    return SimpleNamespace(content=content, span=_span(offset, len(content)), confidence=confidence)


def _fake_analyze_result() -> SimpleNamespace:
    words = [_word("Hemoglobin", 0, 0.99), _word("14.2", 11, 0.62)]
    line = SimpleNamespace(content="Hemoglobin 14.2", spans=[_span(0, 15)])
    empty_line = SimpleNamespace(content="", spans=[_span(100, 0)])
    page = SimpleNamespace(page_number=1, words=words, lines=[line, empty_line])
    table = SimpleNamespace(
        row_count=2,
        column_count=2,
        cells=[
            SimpleNamespace(row_index=0, column_index=0, content="Analyte"),
            SimpleNamespace(row_index=0, column_index=1, content="Value"),
        ],
    )
    return SimpleNamespace(content="Hemoglobin 14.2", pages=[page], tables=[table])


def _client_with_stub_poller(mocker, poller_result=None, poller_error=None):
    poller = mocker.Mock()
    if poller_error is not None:
        poller.result.side_effect = poller_error
    else:
        poller.result.return_value = poller_result
    stub_sdk_client = mocker.Mock()
    stub_sdk_client.begin_analyze_document.return_value = poller
    mocker.patch("di_client.DocumentIntelligenceClient", return_value=stub_sdk_client)
    mocker.patch("di_client.DocumentIntelligenceAdministrationClient")
    return DIClient(endpoint="https://example.cognitiveservices.azure.com", api_key="fake-key"), stub_sdk_client


def _client_with_stub_admin(mocker, admin_error=None):
    stub_admin_client = mocker.Mock()
    if admin_error is not None:
        stub_admin_client.get_resource_details.side_effect = admin_error
    mocker.patch("di_client.DocumentIntelligenceClient")
    mocker.patch("di_client.DocumentIntelligenceAdministrationClient", return_value=stub_admin_client)
    client = DIClient(endpoint="https://example.cognitiveservices.azure.com", api_key="fake-key")
    return client, stub_admin_client


def test_ping_succeeds_when_resource_details_reachable(mocker):
    client, stub_admin_client = _client_with_stub_admin(mocker)

    client.ping()

    stub_admin_client.get_resource_details.assert_called_once()


def test_ping_raises_document_intelligence_error_on_failure(mocker):
    client, _ = _client_with_stub_admin(
        mocker, admin_error=HttpResponseError(message="unauthorized")
    )

    with pytest.raises(DocumentIntelligenceError):
        client.ping()


def test_analyze_layout_extracts_text_tables_and_confidence(mocker):
    client, _ = _client_with_stub_poller(mocker, poller_result=_fake_analyze_result())

    result = client.analyze_layout(b"%PDF-fake-bytes")

    assert result.content == "Hemoglobin 14.2"
    assert len(result.tables) == 1
    assert result.tables[0].row_count == 2
    assert result.tables[0].cells[1].content == "Value"

    assert len(result.pages) == 1
    page = result.pages[0]
    assert [w.content for w in page.words] == ["Hemoglobin", "14.2"]
    assert page.words[1].confidence == pytest.approx(0.62)


def test_line_confidence_is_mean_of_contained_words(mocker):
    client, _ = _client_with_stub_poller(mocker, poller_result=_fake_analyze_result())

    result = client.analyze_layout(b"%PDF-fake-bytes")

    line = result.pages[0].lines[0]
    assert line.confidence == pytest.approx((0.99 + 0.62) / 2)


def test_line_with_no_matching_words_has_none_confidence(mocker):
    client, _ = _client_with_stub_poller(mocker, poller_result=_fake_analyze_result())

    result = client.analyze_layout(b"%PDF-fake-bytes")

    empty_line = result.pages[0].lines[1]
    assert empty_line.confidence is None


def test_analyze_layout_wraps_service_errors(mocker):
    client, _ = _client_with_stub_poller(
        mocker, poller_error=HttpResponseError(message="corrupt document")
    )

    with pytest.raises(DocumentIntelligenceError):
        client.analyze_layout(b"not-a-real-document")


def test_analyze_layout_passes_raw_bytes_to_sdk(mocker):
    client, stub_sdk_client = _client_with_stub_poller(mocker, poller_result=_fake_analyze_result())

    client.analyze_layout(b"%PDF-fake-bytes")

    stub_sdk_client.begin_analyze_document.assert_called_once_with("prebuilt-layout", body=b"%PDF-fake-bytes")