from __future__ import annotations

import csv
import io
import json
import zipfile
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree

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


def _nested(value: Any, path: str | None) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _xml_to_dict(element: ElementTree.Element) -> dict[str, Any]:
    children = list(element)
    if not children:
        return {element.tag: element.text or ""}
    result: dict[str, Any] = {}
    for child in children:
        child_value = _xml_to_dict(child)[child.tag]
        if child.tag in result:
            existing = result[child.tag]
            if not isinstance(existing, list):
                result[child.tag] = [existing]
            result[child.tag].append(child_value)
        else:
            result[child.tag] = child_value
    if element.attrib:
        result["@attributes"] = dict(element.attrib)
    return {element.tag: result}


class OfficialDataConnector(BaseConnector):
    name = "official"
    version = "1.0.0"

    def __init__(self, http: ResilientHttpClient | None = None):
        self.http = http

    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        config = context.config
        url = config.get("url")
        if not url:
            raise ConnectorError("official connector requires config.url")
        page_param = config.get("page_param")
        page = int((context.cursor or {}).get("page", config.get("page_start", 1)))
        max_pages = int(config.get("max_pages", 1))
        for _ in range(max_pages):
            params = dict(config.get("params", {}))
            params.update(
                {
                    config.get("window_start_param", "from"): context.window.start.isoformat(),
                    config.get("window_end_param", "to"): context.window.end.isoformat(),
                }
            )
            if page_param:
                params[page_param] = page
            http = self.http or ResilientHttpClient()
            self.http = http
            response = http.get(url, params=params)
            media_type = response.headers.get("content-type", "application/octet-stream").split(
                ";"
            )[0]
            artifacts, raw_records, quarantined = self._decode(
                response.content,
                config.get("format", "auto"),
                media_type,
                config.get("records_path", "results"),
            )
            records: list[SourceRecordCandidate] = []
            id_field = config.get("id_field", "id")
            for row in raw_records:
                external_id = _nested(row, id_field)
                if external_id in (None, ""):
                    quarantined.append(
                        QuarantineCandidate(
                            reason_code="missing_external_id",
                            message=f"record missing configured id field {id_field}",
                            payload=row,
                        )
                    )
                    continue
                attachment_urls = []
                for attachment_path in config.get("attachment_paths", []):
                    value = _nested(row, attachment_path)
                    if isinstance(value, list):
                        attachment_urls.extend(str(item) for item in value)
                    elif value:
                        attachment_urls.append(str(value))
                deadline_field = config.get("deadline_field")
                effective_field = config.get("effective_at_field")
                revoked_field = config.get("revoked_field")
                deadline_value = _nested(row, deadline_field) if deadline_field else None
                effective_value = _nested(row, effective_field) if effective_field else None
                revoked_value = _nested(row, revoked_field) if revoked_field else None
                records.append(
                    SourceRecordCandidate(
                        external_id=str(external_id),
                        payload=row,
                        artifact_index=0,
                        deadline=isoparse(str(deadline_value)) if deadline_value else None,
                        effective_at=isoparse(str(effective_value)) if effective_value else None,
                        revoked=revoked_value
                        in config.get(
                            "revoked_values", ["cancelled", "withdrawn", "revoked", True]
                        ),
                        relation={"attachment_urls": attachment_urls},
                    )
                )
            body = response.json() if media_type.endswith("json") else None
            next_path = config.get("next_cursor_path")
            has_more_path = config.get("has_more_path")
            next_value = _nested(body, next_path) if body and next_path else None
            has_more = bool(_nested(body, has_more_path)) if body and has_more_path else False
            page += 1
            next_cursor = {"page": page}
            yield ConnectorBatch(
                artifacts=[
                    ArtifactCandidate(
                        content=response.content,
                        media_type=media_type,
                        source_url=str(response.url),
                        metadata={"http_status": response.status_code, "page": page - 1},
                    ),
                    *artifacts,
                ],
                records=records,
                quarantined=quarantined,
                next_cursor={"token": next_value} if next_value is not None else next_cursor,
                metrics={"records": len(records), "quarantined": len(quarantined)},
            )
            if next_value is None and not has_more:
                break

    def _decode(
        self,
        content: bytes,
        requested_format: str,
        media_type: str,
        records_path: str | None = "results",
    ) -> tuple[list[ArtifactCandidate], list[dict[str, Any]], list[QuarantineCandidate]]:
        data_format = self._format(requested_format, media_type, content)
        if data_format == "zip":
            return self._decode_zip(content)
        if data_format == "json":
            body = json.loads(content)
            records = body if isinstance(body, list) else _nested(body, records_path) or [body]
            return [], list(records), []
        if data_format == "csv":
            text = content.decode("utf-8-sig")
            return [], list(csv.DictReader(io.StringIO(text))), []
        if data_format == "xml":
            root = ElementTree.fromstring(content)
            rows = [_xml_to_dict(child)[child.tag] for child in list(root)]
            return [], rows, []
        raise ConnectorError(f"unsupported official data format: {data_format}")

    def _decode_zip(
        self, content: bytes
    ) -> tuple[list[ArtifactCandidate], list[dict[str, Any]], list[QuarantineCandidate]]:
        artifacts: list[ArtifactCandidate] = []
        records: list[dict[str, Any]] = []
        quarantined: list[QuarantineCandidate] = []
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if info.is_dir() or ".." in path.parts:
                    continue
                data = archive.read(info)
                suffix = path.suffix.lower()
                media_type = {
                    ".json": "application/json",
                    ".csv": "text/csv",
                    ".xml": "application/xml",
                }.get(suffix)
                if media_type is None:
                    quarantined.append(
                        QuarantineCandidate(
                            reason_code="unsupported_archive_member",
                            message=f"unsupported member {info.filename}",
                        )
                    )
                    continue
                artifacts.append(
                    ArtifactCandidate(
                        content=data,
                        media_type=media_type,
                        source_url=f"zip://{info.filename}",
                        metadata={"archive_member": info.filename},
                    )
                )
                _, member_records, member_quarantine = self._decode(data, "auto", media_type)
                records.extend(member_records)
                quarantined.extend(member_quarantine)
        return artifacts, records, quarantined

    @staticmethod
    def _format(requested: str, media_type: str, content: bytes) -> str:
        if requested != "auto":
            return requested
        if content.startswith(b"PK\x03\x04"):
            return "zip"
        if "json" in media_type:
            return "json"
        if "csv" in media_type:
            return "csv"
        if "xml" in media_type:
            return "xml"
        stripped = content.lstrip()
        if stripped.startswith((b"{", b"[")):
            return "json"
        if stripped.startswith(b"<"):
            return "xml"
        return "csv"
