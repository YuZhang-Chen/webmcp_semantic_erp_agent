from __future__ import annotations

import base64
import json
import os
import ssl
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


class ODataError(RuntimeError):
    pass


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes


Transport = Callable[[Request, float, ssl.SSLContext], HttpResponse]


def _default_transport(request: Request, timeout: float, context: ssl.SSLContext) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return HttpResponse(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as exc:
        body = exc.read(4096)
        raise ODataError(f"SAP OData returned HTTP {exc.code}: {body.decode('utf-8', 'replace')}") from exc
    except URLError as exc:
        raise ODataError(f"SAP OData connection failed: {exc.reason}") from exc


def parse_rows(payload: dict[str, Any], protocol: str) -> tuple[list[dict[str, Any]], str]:
    if protocol == "odata-v2":
        body = payload.get("d")
        if isinstance(body, list):
            return body, ""
        if not isinstance(body, dict):
            raise ODataError("OData V2 response must contain d")
        rows = body.get("results")
        if rows is None:
            rows = [body]
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ODataError("OData V2 d.results must be an array of objects")
        return rows, str(body.get("__next") or "")
    if protocol == "odata-v4":
        rows = payload.get("value")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ODataError("OData V4 response must contain a value array")
        return rows, str(payload.get("@odata.nextLink") or payload.get("odata.nextLink") or "")
    raise ODataError(f"unsupported protocol: {protocol}")


def odata_literal(value: Any, value_type: str, protocol: str, *, end_of_day: bool = False) -> str:
    if value_type in {"integer", "number"}:
        return str(value)
    if value_type == "boolean":
        return "true" if bool(value) else "false"
    text = str(value).replace("'", "''")
    if value_type == "date":
        if protocol == "odata-v2":
            suffix = "T23:59:59" if end_of_day else "T00:00:00"
            return f"datetime'{text}{suffix}'"
        return text
    return f"'{text}'"


class ODataClient:
    def __init__(
        self,
        base_url: str,
        protocol: str,
        *,
        timeout_seconds: float = 30.0,
        max_pages: int = 5,
        username: str = "",
        password: str = "",
        ca_bundle: str = "",
        transport: Transport | None = None,
    ) -> None:
        if protocol not in {"odata-v2", "odata-v4"}:
            raise ODataError("protocol must be odata-v2 or odata-v4")
        if not base_url.startswith(("https://", "http://")):
            raise ODataError("base_url must be an absolute HTTP(S) URL")
        self.base_url = base_url.rstrip("/") + "/"
        self.protocol = protocol
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.username = username
        self.password = password
        self.context = ssl.create_default_context(cafile=ca_bundle or None)
        self.transport = transport or _default_transport

    @classmethod
    def from_environment(
        cls, base_url: str, protocol: str, *, max_pages: int, timeout_seconds: float
    ) -> "ODataClient":
        return cls(
            base_url,
            protocol,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
            username=os.environ.get("SAP_ODATA_USERNAME", ""),
            password=os.environ.get("SAP_ODATA_PASSWORD", ""),
            ca_bundle=os.environ.get("SAP_ODATA_CA_BUNDLE", ""),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "erp-webmcp-research/0.1"}
        if self.protocol == "odata-v4":
            headers["OData-Version"] = "4.0"
        else:
            headers["DataServiceVersion"] = "2.0"
        if self.username:
            token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    def get(self, entity_set: str, query: dict[str, str]) -> tuple[list[dict[str, Any]], str]:
        initial = urljoin(self.base_url, entity_set)
        if query:
            initial += "?" + urlencode(query, safe="$(),'/")
        expected_origin = urlsplit(self.base_url)[:2]
        current = initial
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        request_id = ""
        for _page in range(self.max_pages):
            if current in seen:
                raise ODataError("repeated OData nextLink")
            seen.add(current)
            if urlsplit(current)[:2] != expected_origin:
                raise ODataError("OData nextLink changed origin")
            request = Request(current, headers=self._headers(), method="GET")
            response = self.transport(request, self.timeout_seconds, self.context)
            if response.status < 200 or response.status >= 300:
                raise ODataError(f"SAP OData returned HTTP {response.status}")
            request_id = response.headers.get("x-request-id", request_id)
            try:
                payload = json.loads(response.body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ODataError("SAP OData response is not valid UTF-8 JSON") from exc
            page_rows, next_link = parse_rows(payload, self.protocol)
            rows.extend(page_rows)
            if not next_link:
                return rows, request_id
            current = urljoin(current, next_link)
        raise ODataError(f"OData response exceeded max_pages={self.max_pages}")
