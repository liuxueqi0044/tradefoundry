from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from dateutil.parser import isoparse

from tradefoundry.ingestion.connectors.base import (
    BaseConnector,
    ConnectorError,
    ResilientHttpClient,
)
from tradefoundry.ingestion.contracts import (
    ArtifactCandidate,
    ConnectorBatch,
    ConnectorContext,
    QuarantineCandidate,
    SourceRecordCandidate,
)
from tradefoundry.ingestion.hashing import canonical_json_bytes


class OCDSConnector(BaseConnector):
    """OCDS release/record package adapter, including Kingfisher Process exports."""

    name = "ocds"
    version = "1.0.0"

    def __init__(self, http: ResilientHttpClient | None = None):
        self.http = http

    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        config = context.config
        if "payload" in config:
            payload = config["payload"]
            content = canonical_json_bytes(payload)
            source_url = "embedded://ocds"
        elif config.get("url"):
            http = self.http or ResilientHttpClient()
            self.http = http
            response = http.get(config["url"], params=config.get("params"))
            content = response.content
            source_url = str(response.url)
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise ConnectorError("OCDS endpoint did not return JSON") from exc
        else:
            raise ConnectorError("OCDS connector requires config.payload or config.url")

        records: list[SourceRecordCandidate] = []
        quarantined: list[QuarantineCandidate] = []
        package_meta = {
            "uri": payload.get("uri"),
            "version": payload.get("version"),
            "publishedDate": payload.get("publishedDate"),
            "publisher": payload.get("publisher"),
        }
        if isinstance(payload.get("releases"), list):
            for release in payload["releases"]:
                ocid = release.get("ocid")
                release_id = release.get("id")
                if not ocid or not release_id:
                    quarantined.append(self._invalid("release", release))
                    continue
                records.append(
                    SourceRecordCandidate(
                        external_id=f"release:{ocid}:{release_id}",
                        payload=release,
                        artifact_index=0,
                        revoked=bool(release.get("tender", {}).get("status") == "cancelled"),
                        effective_at=self._date(release.get("date")),
                        deadline=self._date(
                            release.get("tender", {}).get("tenderPeriod", {}).get("endDate")
                        ),
                        relation={"kind": "release", "ocid": ocid, "package": package_meta},
                    )
                )
        elif isinstance(payload.get("records"), list):
            for record in payload["records"]:
                ocid = record.get("ocid")
                if not ocid:
                    quarantined.append(self._invalid("record", record))
                    continue
                records.append(
                    SourceRecordCandidate(
                        external_id=f"record:{ocid}",
                        payload=record,
                        artifact_index=0,
                        effective_at=self._date(record.get("compiledRelease", {}).get("date")),
                        deadline=self._date(
                            record.get("compiledRelease", {})
                            .get("tender", {})
                            .get("tenderPeriod", {})
                            .get("endDate")
                        ),
                        relation={
                            "kind": "record",
                            "ocid": ocid,
                            "release_ids": [
                                item.get("id")
                                for item in record.get("releases", [])
                                if item.get("id")
                            ],
                            "has_compiled_release": bool(record.get("compiledRelease")),
                            "package": package_meta,
                        },
                    )
                )
                compiled = record.get("compiledRelease")
                if compiled:
                    records.append(
                        SourceRecordCandidate(
                            external_id=f"compiled:{ocid}",
                            payload=compiled,
                            artifact_index=0,
                            effective_at=self._date(compiled.get("date")),
                            deadline=self._date(
                                compiled.get("tender", {}).get("tenderPeriod", {}).get("endDate")
                            ),
                            relation={
                                "kind": "compiled_release",
                                "ocid": ocid,
                                "record_external_id": f"record:{ocid}",
                                "package": package_meta,
                            },
                        )
                    )
        else:
            quarantined.append(
                QuarantineCandidate(
                    reason_code="invalid_ocds_package",
                    message="package must contain releases[] or records[]",
                    payload=payload,
                )
            )

        yield ConnectorBatch(
            artifacts=[
                ArtifactCandidate(
                    content=content,
                    media_type="application/json",
                    source_url=source_url,
                    metadata={"standard": "OCDS", "package": package_meta},
                )
            ],
            records=records,
            quarantined=quarantined,
            next_cursor={"publishedDate": package_meta["publishedDate"]},
            metrics={"records": len(records), "quarantined": len(quarantined)},
        )

    @staticmethod
    def _invalid(kind: str, payload: dict[str, Any]) -> QuarantineCandidate:
        return QuarantineCandidate(
            reason_code=f"invalid_ocds_{kind}",
            message=f"{kind} lacks required OCDS identifiers",
            payload=payload,
        )

    @staticmethod
    def _date(value: str | None):
        return isoparse(value) if value else None
