import io
import zipfile

import pytest

from tradefoundry.evidence.intake import FileIntakeService, IntakePolicy


def test_size_limit_and_mime_spoof_are_quarantined(session, artifact_store):
    limited = FileIntakeService(session, artifact_store, policy=IntakePolicy(max_bytes=3)).ingest(
        logical_document_id="oversize",
        filename="large.txt",
        content=b"four",
        declared_media_type="text/plain",
    )
    spoof = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="spoof",
        filename="fake.pdf",
        content=b"plain text",
        declared_media_type="application/pdf",
    )

    assert limited.status == "quarantined"
    assert limited.artifact_sha256 is None
    assert "size limit" in limited.quarantine_reason
    assert spoof.status == "quarantined"
    assert "does not match" in spoof.quarantine_reason


def test_archive_path_traversal_and_damage_are_quarantined(session, artifact_store):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.txt", "unsafe")
    traversal = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="zip-traversal",
        filename="files.zip",
        content=stream.getvalue(),
        declared_media_type="application/zip",
    )
    damaged = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="zip-damaged",
        filename="broken.zip",
        content=b"PK\x03\x04not-a-valid-archive",
        declared_media_type="application/zip",
    )

    assert "path traversal" in traversal.quarantine_reason
    assert "damaged archive" in damaged.quarantine_reason


def test_test_malware_signature_is_never_promoted(session, artifact_store):
    document = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="malware",
        filename="sample.txt",
        content=b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE",
        declared_media_type="text/plain",
    )

    assert document.status == "quarantined"
    assert document.artifact_sha256 is None
    assert "EICAR" in document.quarantine_reason


def test_office_open_xml_is_detected_from_container_not_extension(session, artifact_store):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    document = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="office",
        filename="notice.docx",
        content=stream.getvalue(),
        declared_media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    assert document.status == "accepted"
    assert document.detected_media_type.endswith("wordprocessingml.document")


def test_unsafe_filename_and_macro_extension_are_quarantined(session, artifact_store):
    service = FileIntakeService(session, artifact_store)
    unsafe = service.ingest(
        logical_document_id="unsafe-name",
        filename="../notice.txt",
        content=b"content",
        declared_media_type="text/plain",
    )
    macro = service.ingest(
        logical_document_id="macro",
        filename="notice.docm",
        content=b"plain content",
        declared_media_type="text/plain",
    )

    assert unsafe.quarantine_reason == "unsafe filename"
    assert "macro-enabled" in macro.quarantine_reason


def test_production_refuses_development_only_scanner(session, artifact_store):
    with pytest.raises(ValueError, match="real malware scanner"):
        FileIntakeService(session, artifact_store, production=True)
