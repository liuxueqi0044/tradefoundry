from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from tradefoundry.ingestion.connectors.base import (
    BaseConnector,
    ConnectorError,
    ConnectorPolicyError,
    ResilientHttpClient,
)
from tradefoundry.ingestion.contracts import (
    ArtifactCandidate,
    ConnectorBatch,
    ConnectorContext,
    QuarantineCandidate,
    SourceRecordCandidate,
)
from tradefoundry.ingestion.hashing import payload_hash


class AuthorizedWebConnector(BaseConnector):
    name = "authorized_web"
    version = "1.0.0"

    def __init__(self, http: ResilientHttpClient | None = None):
        self.http = http

    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        config = context.config
        if config.get("policy_decision") != "allow":
            raise ConnectorPolicyError("web acquisition requires policy_decision=allow")
        if config.get("robots_allowed") is not True:
            raise ConnectorPolicyError("web acquisition requires robots_allowed=true")
        if not config.get("robots_checked_at"):
            raise ConnectorPolicyError("web acquisition requires robots_checked_at")
        if not config.get("permission_basis"):
            raise ConnectorPolicyError("web acquisition requires permission_basis")
        urls = config.get("urls") or ([config["url"]] if config.get("url") else [])
        if not urls:
            raise ConnectorError("authorized web connector requires url or urls")

        http = self.http or ResilientHttpClient()
        self.http = http
        for index, url in enumerate(urls):
            response = http.get(url)
            html = response.content
            soup = BeautifulSoup(html, "html.parser")
            missing = [
                selector
                for selector in config.get("required_selectors", [])
                if not soup.select(selector)
            ]
            if missing:
                yield ConnectorBatch(
                    artifacts=[
                        ArtifactCandidate(
                            content=html,
                            media_type="text/html",
                            source_url=str(response.url),
                            metadata={"policy_decision": "allow", "robots_allowed": True},
                        )
                    ],
                    quarantined=[
                        QuarantineCandidate(
                            reason_code="dom_contract_failed",
                            message="missing selectors: " + ", ".join(missing),
                            payload={"url": str(response.url)},
                        )
                    ],
                    next_cursor={"url_index": index + 1},
                    metrics={"records": 0, "dom_contract_failures": 1},
                )
                continue

            fields: dict[str, str | list[str] | None] = {}
            for field, selector in config.get("field_selectors", {}).items():
                nodes = soup.select(selector)
                values = [node.get_text(" ", strip=True) for node in nodes]
                fields[field] = (
                    values
                    if config.get("multi_fields", {}).get(field)
                    else (values[0] if values else None)
                )
            attachments = [
                urljoin(str(response.url), node.get("href"))
                for node in soup.select(config.get("attachment_selector", "a[href]"))
                if node.get("href")
            ]
            payload = {
                "url": str(response.url),
                "title": soup.title.get_text(strip=True) if soup.title else None,
                "fields": fields,
                "attachments": attachments,
                "dom_fingerprint": payload_hash(
                    {"tags": [node.name for node in soup.find_all(True)], "fields": fields}
                ),
            }
            external_id = fields.get(config.get("id_field", "id")) or payload_hash(
                str(response.url)
            )
            yield ConnectorBatch(
                artifacts=[
                    ArtifactCandidate(
                        content=html,
                        media_type="text/html",
                        source_url=str(response.url),
                        metadata={"policy_decision": "allow", "robots_allowed": True},
                    )
                ],
                records=[
                    SourceRecordCandidate(
                        external_id=str(external_id), payload=payload, artifact_index=0
                    )
                ],
                next_cursor={"url_index": index + 1},
                metrics={"records": 1, "attachments": len(attachments)},
            )
