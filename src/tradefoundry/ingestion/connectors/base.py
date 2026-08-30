from __future__ import annotations

import ipaddress
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from tradefoundry.ingestion.contracts import ConnectorBatch, ConnectorContext


class ConnectorError(RuntimeError):
    pass


class ConnectorPolicyError(ConnectorError):
    pass


def validate_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConnectorPolicyError("connector URL must use public http or https")
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ConnectorPolicyError("connector URL cannot target localhost")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ConnectorPolicyError("connector URL cannot target a non-public IP address")


class BaseConnector(ABC):
    name: str
    version: str

    @abstractmethod
    def fetch(self, context: ConnectorContext) -> Iterable[ConnectorBatch]:
        """Yield bounded batches and a durable cursor after each batch."""


class ResilientHttpClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout_seconds: float = 30,
        user_agent: str = "TradeFoundry/0.1",
        minimum_interval_seconds: float = 0,
    ):
        self.client = client or httpx.Client(
            timeout=timeout_seconds, headers={"User-Agent": user_agent}, follow_redirects=False
        )
        self.minimum_interval_seconds = minimum_interval_seconds
        self._last_request_at = 0.0

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        wait=wait_exponential(multiplier=0.25, min=0.25, max=4),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        current_url = url
        current_params = params
        for _ in range(6):
            validate_fetch_url(current_url)
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.minimum_interval_seconds:
                time.sleep(self.minimum_interval_seconds - elapsed)
            response = self.client.get(current_url, params=current_params)
            self._last_request_at = time.monotonic()
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    response.raise_for_status()
                current_url = urljoin(str(response.url), location)
                current_params = None
                continue
            response.raise_for_status()
            return response
        raise ConnectorError("too many HTTP redirects")
