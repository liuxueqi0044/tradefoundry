from __future__ import annotations

import io
import mimetypes
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Protocol
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradefoundry.evidence.contracts import EvidenceDocumentView
from tradefoundry.evidence.models import EvidenceDocumentRow
from tradefoundry.ingestion.artifacts import FileSystemArtifactStore
from tradefoundry.ingestion.contracts import ArtifactCandidate
from tradefoundry.ingestion.hashing import bytes_hash
from tradefoundry.ingestion.models import ArtifactBlobRow


class ScanVerdict(StrEnum):
    CLEAN = "clean"
    MALICIOUS = "malicious"
    ERROR = "error"


class MalwareScanner(Protocol):
    name: str

    def scan(self, content: bytes, filename: str) -> tuple[ScanVerdict, str | None]: ...


class DevelopmentPatternScanner:
    """Minimal local safety tripwire; production must replace it with an AV adapter."""

    name = "development-pattern-scanner"

    def scan(self, content: bytes, filename: str) -> tuple[ScanVerdict, str | None]:
        del filename
        if b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE" in content:
            return ScanVerdict.MALICIOUS, "EICAR test signature detected"
        return ScanVerdict.CLEAN, None


@dataclass(frozen=True)
class IntakePolicy:
    max_bytes: int = 50 * 1024 * 1024
    max_archive_members: int = 2_000
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    max_compression_ratio: float = 100.0


MEDIA_ALIASES = {
    "application/x-pdf": "application/pdf",
    "text/x-markdown": "text/markdown",
    "application/vnd.ms-word.document.macroenabled.12": "application/macro-enabled",
}


class FileIntakeService:
    def __init__(
        self,
        session: Session,
        artifact_store: FileSystemArtifactStore,
        *,
        scanner: MalwareScanner | None = None,
        policy: IntakePolicy | None = None,
        production: bool = False,
    ):
        self.session = session
        self.artifact_store = artifact_store
        self.scanner = scanner or DevelopmentPatternScanner()
        self.policy = policy or IntakePolicy()
        if production and isinstance(self.scanner, DevelopmentPatternScanner):
            raise ValueError("production intake requires a real malware scanner adapter")

    def ingest(
        self,
        *,
        logical_document_id: str,
        filename: str,
        content: bytes,
        declared_media_type: str | None = None,
        source_url: str | None = None,
        metadata: dict | None = None,
    ) -> EvidenceDocumentView:
        version_no = self._next_version(logical_document_id)
        digest = bytes_hash(content)
        detected, issue = self._inspect(filename, content, declared_media_type)
        artifact_sha: str | None = None
        security_status = "rejected"
        status = "quarantined"

        if issue is None:
            verdict, scan_reason = self.scanner.scan(content, filename)
            security_status = f"{self.scanner.name}:{verdict.value}"
            if verdict == ScanVerdict.CLEAN:
                reference = self.artifact_store.put(
                    ArtifactCandidate(content=content, media_type=detected, source_url=source_url)
                )
                artifact_sha = reference.sha256
                blob = self.session.get(ArtifactBlobRow, reference.sha256)
                if blob is None:
                    self.session.add(
                        ArtifactBlobRow(
                            sha256=reference.sha256,
                            uri=reference.uri,
                            size_bytes=reference.size_bytes,
                            media_type=reference.media_type,
                        )
                    )
                status = "accepted"
            else:
                issue = scan_reason or f"malware scan returned {verdict.value}"

        row = EvidenceDocumentRow(
            id=str(uuid4()),
            logical_document_id=logical_document_id,
            version_no=version_no,
            content_sha256=digest,
            artifact_sha256=artifact_sha,
            filename=filename,
            source_url=source_url,
            declared_media_type=declared_media_type,
            detected_media_type=detected,
            size_bytes=len(content),
            status=status,
            security_status=security_status,
            quarantine_reason=issue,
            metadata_json=metadata or {},
        )
        self.session.add(row)
        self.session.commit()
        return EvidenceDocumentView.model_validate(row)

    def _next_version(self, logical_document_id: str) -> int:
        current = self.session.scalar(
            select(func.max(EvidenceDocumentRow.version_no)).where(
                EvidenceDocumentRow.logical_document_id == logical_document_id
            )
        )
        return (current or 0) + 1

    def _inspect(
        self, filename: str, content: bytes, declared_media_type: str | None
    ) -> tuple[str, str | None]:
        if PurePath(filename).name != filename or "\x00" in filename:
            return "application/octet-stream", "unsafe filename"
        if not content:
            return "application/octet-stream", "empty file"
        if len(content) > self.policy.max_bytes:
            return "application/octet-stream", "file exceeds configured size limit"

        detected = detect_media_type(content, filename)
        if detected == "application/zip":
            issue, office_media_type = self._inspect_archive(content)
            if issue:
                return detected, issue
            detected = office_media_type or detected

        extension = PurePath(filename).suffix.lower()
        if extension in {".docm", ".xlsm", ".pptm"}:
            return "application/macro-enabled", "macro-enabled office files are not accepted"
        if detected == "application/octet-stream":
            return detected, "unsupported or unrecognized file type"

        declared = normalize_media_type(declared_media_type)
        if declared and declared != "application/octet-stream":
            compatible = declared == detected or (
                declared.startswith("text/") and detected.startswith("text/")
            )
            if not compatible:
                return detected, f"declared MIME {declared} does not match detected {detected}"
        return detected, None

    def _inspect_archive(self, content: bytes) -> tuple[str | None, str | None]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > self.policy.max_archive_members:
                    return "archive contains too many members", None
                total = sum(member.file_size for member in members)
                if total > self.policy.max_archive_uncompressed_bytes:
                    return "archive expands beyond configured size limit", None
                for member in members:
                    path = PurePath(member.filename.replace("\\", "/"))
                    if path.is_absolute() or ".." in path.parts:
                        return "archive contains path traversal", None
                    if member.flag_bits & 0x1:
                        return "encrypted archive members are not accepted", None
                    compressed = max(member.compress_size, 1)
                    if member.file_size / compressed > self.policy.max_compression_ratio:
                        return "archive compression ratio exceeds safety limit", None
                names = {member.filename.lower() for member in members}
                if "[content_types].xml" in names:
                    if any(name.startswith("word/") for name in names):
                        return None, (
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )
                    if any(name.startswith("ppt/") for name in names):
                        return None, (
                            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                        )
                    if any(name.startswith("xl/") for name in names):
                        return None, (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                return None, None
        except (zipfile.BadZipFile, OSError, RuntimeError):
            return "damaged archive", None


def normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    return MEDIA_ALIASES.get(normalized, normalized)


def detect_media_type(content: bytes, filename: str) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if content.startswith(b"PK\x03\x04"):
        return "application/zip"
    head = content[:4096].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<head", b"<body")):
        return "text/html"
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    guessed, _ = mimetypes.guess_type(filename)
    if guessed in {"application/json", "text/markdown", "text/plain", "text/csv"}:
        return guessed
    return "text/plain"
