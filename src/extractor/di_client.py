"""Azure Document Intelligence client: `prebuilt-layout` OCR/table extraction.

Wraps `DocumentIntelligenceClient` behind a small, dependency-light result type
(`LayoutResult`) so callers and tests don't depend on the Azure SDK's model
classes directly.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult, DocumentLine, DocumentWord
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError

logger = logging.getLogger(__name__)

_MODEL_ID = "prebuilt-layout"


class DocumentIntelligenceError(Exception):
    """Raised when DI cannot analyze a document (corrupt/unreadable input, service error).

    Callers (batch.py) catch this to log, skip, and continue rather than crash the batch.
    """


@dataclass
class WordConfidence:
    content: str
    confidence: float


@dataclass
class Line:
    content: str
    confidence: float | None
    """Mean confidence of the words making up this line. DI reports confidence only at the
    word level, not the line level, so this is derived — `None` if no word matched the line's
    span (e.g. a purely visual line)."""


@dataclass
class Page:
    page_number: int
    lines: list[Line] = field(default_factory=list)
    words: list[WordConfidence] = field(default_factory=list)


@dataclass
class TableCell:
    row_index: int
    column_index: int
    content: str


@dataclass
class Table:
    row_count: int
    column_count: int
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class LayoutResult:
    """Structural extraction from one document: reading-order text, tables, and per-word/line
    confidence, keyed by page."""

    content: str
    pages: list[Page] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)


def _line_confidence(line: DocumentLine, words: Sequence[DocumentWord]) -> float | None:
    line_spans = line.spans or []
    matched = [
        word.confidence
        for word in words
        if any(
            span.offset <= word.span.offset
            and word.span.offset + word.span.length <= span.offset + span.length
            for span in line_spans
        )
    ]
    return sum(matched) / len(matched) if matched else None


def _to_layout_result(result: AnalyzeResult) -> LayoutResult:
    pages = []
    for page in result.pages or []:
        words = page.words or []
        lines = [
            Line(content=line.content, confidence=_line_confidence(line, words))
            for line in page.lines or []
        ]
        pages.append(
            Page(
                page_number=page.page_number,
                lines=lines,
                words=[WordConfidence(content=w.content, confidence=w.confidence) for w in words],
            )
        )
    tables = [
        Table(
            row_count=table.row_count,
            column_count=table.column_count,
            cells=[
                TableCell(
                    row_index=cell.row_index,
                    column_index=cell.column_index,
                    content=cell.content,
                )
                for cell in table.cells
            ],
        )
        for table in result.tables or []
    ]
    return LayoutResult(content=result.content, pages=pages, tables=tables)


class DIClient:
    """Thin wrapper over Azure Document Intelligence's `prebuilt-layout` model."""

    def __init__(self, endpoint: str, api_key: str) -> None:
        self._client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(api_key))

    def analyze_layout(self, document_bytes: bytes) -> LayoutResult:
        """Run `prebuilt-layout` on raw document bytes (PDF or image).

        Raises `DocumentIntelligenceError` on unreadable/corrupt input or a DI service
        failure; never lets the underlying SDK exception escape.
        """
        try:
            poller = self._client.begin_analyze_document(_MODEL_ID, body=document_bytes)
            result = poller.result()
        except HttpResponseError as exc:
            logger.error("Document Intelligence analysis failed: %s", exc.message)
            raise DocumentIntelligenceError(str(exc.message)) from exc

        return _to_layout_result(result)
