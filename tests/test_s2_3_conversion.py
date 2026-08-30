import sys
import types

import pytest
from sqlalchemy import func, select

from tradefoundry.evidence.contracts import NormalizedBlock, NormalizedDocument
from tradefoundry.evidence.conversion import ConversionService, DoclingConverterAdapter
from tradefoundry.evidence.models import DocumentConversionRow, EvidenceFragmentRow


class GoldenConverter:
    name = "golden-fixture"
    version = "2.0"

    def convert(self, content: bytes, filename: str, media_type: str) -> NormalizedDocument:
        assert content and filename and media_type
        return NormalizedDocument(
            converter_name=self.name,
            converter_version=self.version,
            page_count=2,
            markdown="# Procurement\n\nDeadline 2026-10-01",
            blocks=[
                NormalizedBlock(
                    key="page-1-heading",
                    kind="heading",
                    text="Procurement",
                    page_no=1,
                    bbox={"left": 10, "top": 20, "right": 200, "bottom": 50},
                    section_path=["Procurement"],
                ),
                NormalizedBlock(
                    key="page-2-table",
                    kind="table",
                    text="Deadline | 2026-10-01",
                    page_no=2,
                    bbox={"left": 30, "top": 100, "right": 500, "bottom": 300},
                    section_path=["Procurement"],
                    table_cell={"row": 1, "column": 2},
                ),
            ],
            errors=[{"page_no": 2, "code": "low_ocr_confidence"}],
        )


def test_conversion_reconstructs_pages_headings_tables_and_reports_page_errors(
    session, artifact_store, evidence_document_factory
):
    document = evidence_document_factory(convert=False)
    service = ConversionService(session, artifact_store)
    result = service.convert(document.id, GoldenConverter())
    repeated = service.convert(document.id, GoldenConverter())

    assert result.id == repeated.id
    assert result.page_count == 2
    assert result.table_count == 1
    assert result.errors_json[0]["page_no"] == 2
    assert session.scalar(select(func.count()).select_from(EvidenceFragmentRow)) == 2


def test_html_converter_removes_executable_content(evidence_document_factory, session):
    document = evidence_document_factory(
        content=b"<html><script>alert(1)</script><h1>Safe</h1><p>Body</p></html>"
    )
    texts = session.scalars(
        select(EvidenceFragmentRow.text).where(EvidenceFragmentRow.document_id == document.id)
    ).all()

    assert texts == ["Safe", "Body"]


def test_conversion_failure_is_audited(session, artifact_store, evidence_document_factory):
    class BrokenConverter:
        name = "broken"
        version = "1"

        def convert(self, content, filename, media_type):
            raise RuntimeError("page decoder crashed")

    document = evidence_document_factory(logical_id="broken", convert=False)
    with pytest.raises(RuntimeError, match="decoder crashed"):
        ConversionService(session, artifact_store).convert(document.id, BrokenConverter())

    row = session.scalar(
        select(DocumentConversionRow).where(DocumentConversionRow.document_id == document.id)
    )
    assert row.status == "failed"
    assert row.errors_json == [{"code": "conversion_failed", "message": "page decoder crashed"}]


def test_docling_v2_adapter_maps_provenance_errors_and_table_cells(monkeypatch):
    class Dumpable:
        def __init__(self, **values):
            self.values = values

        def model_dump(self, mode="json"):
            assert mode == "json"
            return self.values

    class Cell:
        text = "2026-10-01"
        start_row_offset_idx = 1
        start_col_offset_idx = 2
        row_span = 1
        col_span = 1
        bbox = Dumpable(l=30, t=100, r=200, b=130)

    class Heading:
        label = "section_header"
        text = "Procurement"
        self_ref = "#/texts/0"
        prov = [types.SimpleNamespace(page_no=1, bbox=Dumpable(l=10, t=10, r=200, b=40))]

    class Table:
        label = "table"
        self_ref = "#/tables/0"
        prov = [types.SimpleNamespace(page_no=2, bbox=Dumpable(l=20, t=80, r=500, b=300))]
        data = types.SimpleNamespace(table_cells=[Cell()])

        @staticmethod
        def export_to_markdown():
            return "| Deadline | 2026-10-01 |"

    class FakeDocument:
        @staticmethod
        def iterate_items():
            return iter([(Heading(), 1), (Table(), 2)])

        @staticmethod
        def export_to_markdown():
            return "# Procurement"

    result = types.SimpleNamespace(
        document=FakeDocument(),
        errors=[Dumpable(page_no=2, code="low_ocr_confidence")],
        status="succeeded",
    )
    converter_module = types.ModuleType("docling.document_converter")
    converter_module.DocumentConverter = lambda: types.SimpleNamespace(convert=lambda path: result)
    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    converted = DoclingConverterAdapter().convert(b"fake pdf", "notice.pdf", "application/pdf")

    assert converted.page_count == 2
    assert converted.errors[0]["code"] == "low_ocr_confidence"
    assert [block.kind for block in converted.blocks] == [
        "heading",
        "table",
        "table_cell",
    ]
    assert converted.blocks[2].table_cell["row"] == 1
    assert converted.blocks[2].bbox["l"] == 30
