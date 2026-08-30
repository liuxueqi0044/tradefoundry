from __future__ import annotations

import tempfile
from importlib import metadata
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from tradefoundry.evidence.contracts import (
    ConversionView,
    NormalizedBlock,
    NormalizedDocument,
)
from tradefoundry.evidence.models import (
    DocumentConversionRow,
    EvidenceDocumentRow,
    EvidenceFragmentRow,
)
from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.hashing import payload_hash


class ConverterUnavailableError(RuntimeError):
    pass


class DocumentConversionError(RuntimeError):
    pass


class DocumentConverterPort(Protocol):
    name: str
    version: str

    def convert(self, content: bytes, filename: str, media_type: str) -> NormalizedDocument: ...


class StructuredTextConverter:
    name = "structured-text"
    version = "1.0"

    def convert(self, content: bytes, filename: str, media_type: str) -> NormalizedDocument:
        del filename
        if not media_type.startswith("text/") and media_type != "application/json":
            raise DocumentConversionError(
                f"{self.name} cannot convert media type {media_type}; use Docling"
            )
        text = content.decode("utf-8")
        blocks: list[NormalizedBlock] = []
        markdown = text
        if media_type == "text/html":
            soup = BeautifulSoup(text, "html.parser")
            for unsafe in soup(["script", "style", "iframe", "object", "embed"]):
                unsafe.decompose()
            section_path: list[str] = []
            for index, element in enumerate(
                soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"])
            ):
                value = element.get_text(" ", strip=True)
                if not value:
                    continue
                if element.name and element.name.startswith("h"):
                    level = int(element.name[1])
                    section_path = section_path[: level - 1] + [value]
                    kind = "heading"
                elif element.name == "table":
                    kind = "table"
                else:
                    kind = "text"
                blocks.append(
                    NormalizedBlock(
                        key=f"html:{index}",
                        kind=kind,
                        text=value,
                        section_path=list(section_path),
                    )
                )
            markdown = "\n\n".join(block.text for block in blocks)
        else:
            for index, line in enumerate(line for line in text.splitlines() if line.strip()):
                blocks.append(NormalizedBlock(key=f"line:{index}", kind="text", text=line.strip()))
        return NormalizedDocument(
            converter_name=self.name,
            converter_version=self.version,
            markdown=markdown,
            page_count=1,
            blocks=blocks,
        )


class DoclingConverterAdapter:
    """Lazy adapter around Docling v2; the domain only sees NormalizedDocument."""

    name = "docling"

    @property
    def version(self) -> str:
        try:
            return metadata.version("docling")
        except metadata.PackageNotFoundError:
            return "unavailable"

    def convert(self, content: bytes, filename: str, media_type: str) -> NormalizedDocument:
        del media_type
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ConverterUnavailableError(
                "Docling is not installed; run `uv sync --extra documents`"
            ) from exc

        suffix = Path(filename).suffix or ".bin"
        with tempfile.TemporaryDirectory() as directory:
            document_path = Path(directory) / f"document{suffix}"
            document_path.write_bytes(content)
            result = DocumentConverter().convert(document_path)

        document = result.document
        blocks: list[NormalizedBlock] = []
        headings: list[str] = []
        for index, (item, level) in enumerate(document.iterate_items()):
            label = str(getattr(item, "label", item.__class__.__name__)).lower()
            text = self._item_text(item)
            if not text:
                continue
            kind = "table" if "table" in label else "text"
            if "section_header" in label or "title" in label:
                kind = "heading"
                depth = max(int(level or 1), 1)
                headings = headings[: depth - 1] + [text]
            provenance = list(getattr(item, "prov", []) or [])
            first = provenance[0] if provenance else None
            page_no = getattr(first, "page_no", None)
            bbox = self._model_dump(getattr(first, "bbox", None))
            key = str(getattr(item, "self_ref", None) or f"item:{index}")
            blocks.append(
                NormalizedBlock(
                    key=key,
                    kind=kind,
                    text=text,
                    page_no=page_no,
                    bbox=bbox,
                    section_path=list(headings),
                    metadata={"docling_label": label, "hierarchy_level": level},
                )
            )
            if kind == "table":
                blocks.extend(self._table_cell_blocks(item, key, page_no, headings, index))
        errors = [self._model_dump(error) or {"message": str(error)} for error in result.errors]
        pages = [block.page_no for block in blocks if block.page_no is not None]
        return NormalizedDocument(
            converter_name=self.name,
            converter_version=self.version,
            status=str(getattr(result, "status", "succeeded")).lower(),
            page_count=max(pages, default=None),
            markdown=document.export_to_markdown(),
            blocks=blocks,
            errors=errors,
        )

    @staticmethod
    def _item_text(item) -> str:
        text = getattr(item, "text", None)
        if text:
            return str(text)
        for method_name in ("export_to_markdown", "export_to_html"):
            method = getattr(item, method_name, None)
            if callable(method):
                try:
                    value = method()
                except TypeError:
                    continue
                if value:
                    return str(value)
        return ""

    @classmethod
    def _table_cell_blocks(
        cls, item, table_key: str, page_no: int | None, headings: list[str], table_index: int
    ) -> list[NormalizedBlock]:
        data = getattr(item, "data", None)
        cells = list(getattr(data, "table_cells", []) or [])
        result: list[NormalizedBlock] = []
        for index, cell in enumerate(cells):
            text = str(getattr(cell, "text", "") or "").strip()
            if not text:
                continue
            row = getattr(cell, "start_row_offset_idx", None)
            column = getattr(cell, "start_col_offset_idx", None)
            result.append(
                NormalizedBlock(
                    key=f"{table_key}:cell:{row}:{column}:{index}",
                    kind="table_cell",
                    text=text,
                    page_no=page_no,
                    bbox=cls._model_dump(getattr(cell, "bbox", None)),
                    section_path=list(headings),
                    table_cell={
                        "table_index": table_index,
                        "row": row,
                        "column": column,
                        "row_span": getattr(cell, "row_span", None),
                        "column_span": getattr(cell, "col_span", None),
                    },
                )
            )
        return result

    @staticmethod
    def _model_dump(value):
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return value
        return {"value": str(value)}


class ConversionService:
    def __init__(self, session: Session, artifact_store: FileSystemArtifactStore):
        self.session = session
        self.artifact_store = artifact_store

    def convert(
        self, document_id: str, converter: DocumentConverterPort | None = None
    ) -> ConversionView:
        document = self.session.get(EvidenceDocumentRow, document_id)
        if document is None:
            raise LookupError(f"document {document_id} not found")
        if document.status != "accepted" or document.artifact_sha256 is None:
            raise DocumentConversionError("quarantined documents cannot be converted")
        selected = converter or self._default_converter(document.detected_media_type)
        existing = self.session.scalar(
            select(DocumentConversionRow).where(
                DocumentConversionRow.document_id == document.id,
                DocumentConversionRow.converter_name == selected.name,
                DocumentConversionRow.converter_version == selected.version,
            )
        )
        if existing is not None:
            return ConversionView.model_validate(existing)

        content = self.artifact_store.get(document.artifact_sha256)
        try:
            normalized = selected.convert(content, document.filename, document.detected_media_type)
        except Exception as exc:
            failed = DocumentConversionRow(
                id=str(uuid4()),
                document_id=document.id,
                converter_name=selected.name,
                converter_version=selected.version,
                schema_version="1.0",
                status="failed",
                page_count=None,
                table_count=0,
                markdown="",
                normalized_document_json={},
                errors_json=[{"code": "conversion_failed", "message": str(exc)}],
            )
            self.session.add(failed)
            self.session.commit()
            raise
        row = DocumentConversionRow(
            id=str(uuid4()),
            document_id=document.id,
            converter_name=normalized.converter_name,
            converter_version=normalized.converter_version,
            schema_version=normalized.schema_version,
            status=normalized.status,
            page_count=normalized.page_count,
            table_count=sum(block.kind == "table" for block in normalized.blocks),
            markdown=normalized.markdown,
            normalized_document_json=normalized.model_dump(mode="json"),
            errors_json=normalized.errors,
        )
        self.session.add(row)
        self.session.flush()
        for block in normalized.blocks:
            self.session.add(
                EvidenceFragmentRow(
                    id=str(uuid4()),
                    document_id=document.id,
                    conversion_id=row.id,
                    fragment_key=block.key,
                    fragment_type=block.kind,
                    text=block.text,
                    page_no=block.page_no,
                    bbox_json=block.bbox,
                    section_path=block.section_path,
                    table_cell_json=block.table_cell,
                    content_hash=payload_hash(
                        {
                            "text": block.text,
                            "page_no": block.page_no,
                            "bbox": block.bbox,
                            "table_cell": block.table_cell,
                        }
                    ),
                    metadata_json=block.metadata,
                )
            )
        self.session.commit()
        return ConversionView.model_validate(row)

    @staticmethod
    def _default_converter(media_type: str) -> DocumentConverterPort:
        if media_type.startswith("text/") or media_type == "application/json":
            return StructuredTextConverter()
        return DoclingConverterAdapter()
