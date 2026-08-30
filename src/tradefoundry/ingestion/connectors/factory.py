from __future__ import annotations

from tradefoundry.ingestion.connectors.base import BaseConnector
from tradefoundry.ingestion.connectors.memory import MemoryConnector
from tradefoundry.ingestion.connectors.ocds import OCDSConnector
from tradefoundry.ingestion.connectors.official import OfficialDataConnector
from tradefoundry.ingestion.connectors.web import AuthorizedWebConnector
from tradefoundry.ingestion.contracts import SourceKind


class ConnectorFactory:
    def __init__(self):
        self._connectors: dict[SourceKind, BaseConnector] = {}
        self._providers = {
            SourceKind.MEMORY: MemoryConnector,
            SourceKind.OFFICIAL_API: OfficialDataConnector,
            SourceKind.BULK_FILE: OfficialDataConnector,
            SourceKind.OCDS: OCDSConnector,
            SourceKind.AUTHORIZED_WEB: AuthorizedWebConnector,
        }

    def register(self, kind: SourceKind, connector: BaseConnector) -> None:
        self._connectors[kind] = connector

    def get(self, kind: SourceKind) -> BaseConnector:
        if kind not in self._connectors:
            try:
                self._connectors[kind] = self._providers[kind]()
            except KeyError as exc:
                raise LookupError(f"no connector registered for {kind}") from exc
        return self._connectors[kind]
