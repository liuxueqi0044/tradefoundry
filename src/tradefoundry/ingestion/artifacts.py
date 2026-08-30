from __future__ import annotations

from pathlib import Path

from tradefoundry.ingestion.contracts import ArtifactCandidate, RawArtifactRef
from tradefoundry.ingestion.hashing import bytes_hash


class ArtifactIntegrityError(RuntimeError):
    pass


class FileSystemArtifactStore:
    """Immutable content-addressed byte storage.

    Database observations are stored separately, so the same byte sequence is written once
    even when observed from multiple URLs or sources.
    """

    def __init__(self, root: Path):
        self.root = root

    def put(self, candidate: ArtifactCandidate) -> RawArtifactRef:
        digest = bytes_hash(candidate.content)
        directory = self.root / digest[:2]
        path = directory / digest
        directory.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if bytes_hash(path.read_bytes()) != digest:
                raise ArtifactIntegrityError(f"artifact hash mismatch at {path}")
        else:
            try:
                with path.open("xb") as stream:
                    stream.write(candidate.content)
            except FileExistsError as exc:
                if bytes_hash(path.read_bytes()) != digest:
                    raise ArtifactIntegrityError(
                        f"artifact race produced mismatch at {path}"
                    ) from exc
        return RawArtifactRef(
            sha256=digest,
            uri=path.resolve().as_uri(),
            size_bytes=len(candidate.content),
            media_type=candidate.media_type,
        )

    def get(self, digest: str) -> bytes:
        path = self.root / digest[:2] / digest
        content = path.read_bytes()
        if bytes_hash(content) != digest:
            raise ArtifactIntegrityError(f"artifact hash mismatch at {path}")
        return content
