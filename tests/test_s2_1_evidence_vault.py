import pytest
from sqlalchemy import func, select

from tradefoundry.evidence.intake import FileIntakeService
from tradefoundry.evidence.models import EvidenceDocumentRow
from tradefoundry.ingestion.artifacts import ArtifactIntegrityError
from tradefoundry.ingestion.models import ArtifactBlobRow


def test_content_addressed_storage_deduplicates_bytes_but_versions_documents(
    session, artifact_store
):
    service = FileIntakeService(session, artifact_store)
    values = [
        service.ingest(
            logical_document_id="notice-77",
            filename="notice.txt",
            content=b"immutable evidence",
            declared_media_type="text/plain",
        )
        for _ in range(2)
    ]

    assert [value.version_no for value in values] == [1, 2]
    assert values[0].artifact_sha256 == values[1].artifact_sha256
    assert session.scalar(select(func.count()).select_from(ArtifactBlobRow)) == 1
    assert session.scalar(select(func.count()).select_from(EvidenceDocumentRow)) == 2


def test_vault_rehashes_bytes_on_read(session, artifact_store):
    document = FileIntakeService(session, artifact_store).ingest(
        logical_document_id="notice-78",
        filename="notice.txt",
        content=b"original",
        declared_media_type="text/plain",
    )
    path = artifact_store.root / document.artifact_sha256[:2] / document.artifact_sha256
    path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        artifact_store.get(document.artifact_sha256)
