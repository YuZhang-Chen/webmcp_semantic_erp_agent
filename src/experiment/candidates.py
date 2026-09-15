"""Find Phase 07 SAP pilot candidates from the governed OData bindings.

This module deliberately produces *candidate* evidence only.  It never writes
Ground Truth review or approval state.  The scanner is sequential so that a
researcher can reproduce the request order and inspect failures one order at
a time.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import ssl
import http.client
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlencode, urlparse, urlunparse


ENV_KEYS = {
    "SAP_USER", "SAP_PASSWORD", "SAP_CLIENT", "SAP_LANGUAGE",
    "SAP_ODATA_BASE_URL", "SAP_DELIVERY_ODATA_BASE_URL",
    "SAP_BILLING_ODATA_BASE_URL", "SAP_ODATA_CA_CERT", "SAP_ODATA_CERT_SHA256",
}
SAP_DATE = re.compile(r"^/Date\((\d+)(?:[+-]\d+)?\)/$")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def read_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise RuntimeError(".env file is missing")
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ENV_KEYS or key in result:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def service_root(value: str, key: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{key} must be an absolute HTTPS URL without credentials, query, or fragment")
    return value.strip().rstrip("/") + "/"


def verify_artifact(artifact: Mapping[str, Any]) -> bool:
    expected = artifact.get("artifactSha256")
    if not isinstance(expected, str):
        return False
    unsigned = {key: value for key, value in artifact.items() if key != "artifactSha256"}
    return hashlib.sha256(canonical_bytes(unsigned)).hexdigest() == expected


def escape_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def date_literal(value: str, *, end: bool = False) -> str:
    return f"datetime'{value}T{'23:59:59' if end else '00:00:00'}'"


def normalized_date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return None
    match = SAP_DATE.match(value)
    if match:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, UTC).date().isoformat()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return value[:10]


class ODataTransport(Protocol):
    def get_json(self, service_id: str, entity_set: str, params: Mapping[str, str]) -> dict[str, Any]: ...

    def get_next_json(self, service_id: str, next_url: str) -> dict[str, Any]: ...


@dataclass
class SapGatewayTransport:
    """Bounded HTTPS GET client equivalent to the Phase 06 local gateway."""

    services: Mapping[str, str]
    username: str
    password: str
    client: str
    language: str
    ca_cert: Path
    cert_sha256: str
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if len(self.cert_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.cert_sha256.lower()):
            raise RuntimeError("SAP_ODATA_CERT_SHA256 must be a SHA-256 hex fingerprint")
        if not self.ca_cert.is_file():
            raise RuntimeError("SAP_ODATA_CA_CERT file is missing")

    def get_json(self, service_id: str, entity_set: str, params: Mapping[str, str]) -> dict[str, Any]:
        if service_id not in self.services or not re.fullmatch(r"[A-Za-z0-9_]+", entity_set):
            raise RuntimeError("OData service or entity set is not allowlisted")
        base = self.services[service_id]
        query = dict(params)
        if self.client:
            query["sap-client"] = self.client
        if self.language:
            query["sap-language"] = self.language
        return self._request(service_id, base + entity_set, query)

    def get_next_json(self, service_id: str, next_url: str) -> dict[str, Any]:
        parsed = urlparse(next_url)
        root = urlparse(self.services[service_id])
        if parsed.scheme != root.scheme or parsed.netloc != root.netloc or not parsed.path.startswith(root.path):
            raise RuntimeError("SAP next URL escaped the selected service")
        return self._request(service_id, next_url, dict(__import__("urllib.parse", fromlist=["parse_qsl"]).parse_qsl(parsed.query, keep_blank_values=True)))

    def _request(self, service_id: str, target: str, params: Mapping[str, str]) -> dict[str, Any]:
        parsed = urlparse(target)
        query = urlencode(dict(params))
        path = urlunparse(parsed._replace(scheme="", netloc="", query=query))
        context = ssl.create_default_context(cafile=str(self.ca_cert))
        context.check_hostname = False
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=context, timeout=self.timeout)
        auth = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        try:
            connection.request("GET", path, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
            response = connection.getresponse()
            peer = connection.sock.getpeercert(binary_form=True)
            if hashlib.sha256(peer).hexdigest().lower() != self.cert_sha256.lower():
                raise RuntimeError("SAP certificate pin mismatch")
            body = response.read()
            if response.status < 200 or response.status >= 300:
                error = RuntimeError(f"SAP GET failed with HTTP {response.status}")
                setattr(error, "retryable", response.status in {408, 429, 502, 503, 504})
                raise error
            try:
                value = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("SAP response was not valid JSON") from exc
            if not isinstance(value, dict):
                raise RuntimeError("SAP response root was not an object")
            return value
        finally:
            connection.close()


class CandidateScanner:
    def __init__(self, artifact: Mapping[str, Any], transport: ODataTransport, *, delay_ms: int = 100, max_retries: int = 1):
        if not verify_artifact(artifact):
            raise ValueError("runtime artifact hash verification failed")
        if artifact.get("protocol") != "odata-v2" or artifact.get("policy", {}).get("allowedHttpMethods") != ["GET"]:
            raise ValueError("candidate scanner requires the governed OData GET-only artifact")
        self.artifact = artifact
        self.transport = transport
        self.delay = max(delay_ms, 0) / 1000
        self.max_retries = max_retries
        self.request_count = 0

    def scan(self, criteria: Mapping[str, str], *, limit: int = 30, fail_fast: bool = False) -> dict[str, Any]:
        if not 10 <= limit <= 30:
            raise ValueError("limit must be between 10 and 30")
        if not criteria:
            raise ValueError("at least one governed search criterion is required")
        started = utc_now()
        initial = self._search(criteria, limit)
        candidates: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for order in initial:
            try:
                candidate = self._inspect_order(order)
                candidates.append(candidate)
            except Exception as exc:  # per-order failures are evidence, not a scanner crash
                failure = {"sales_order_id": order.get("sales_order_id"), "error": self._safe_error(exc)}
                failures.append(failure)
                if fail_fast:
                    raise
        candidates.sort(key=self._rank_key)
        assignments = self._assign(candidates)
        return {
            "schema_version": "1.0",
            "classification": "candidate",
            "source_id": self.artifact["model"]["sourceId"],
            "model": self.artifact["model"],
            "runtime_artifact_sha256": self.artifact["artifactSha256"],
            "scanned_at": started,
            "completed_at": utc_now(),
            "scan": {"criteria": dict(criteria), "limit": limit, "sequential": True, "request_count": self.request_count},
            "candidates": candidates,
            "failures": failures,
            "suggested_assignments": assignments,
            "notice": "Candidates require researcher SAP confirmation; this file is not Ground Truth.",
        }

    def _inspect_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        order_id = str(order["sales_order_id"])
        # Re-read each candidate through the canonical single-document operation;
        # the initial collection query is discovery only.
        order = self._get_order(order_id)
        delivery = self._related("get_related_deliveries", order_id, "delivery")
        billing = self._related("get_related_billing_documents", order_id, "billing")
        unique = self._unique_search(order)
        eligible: list[str] = ["P01"]
        if delivery:
            eligible += ["P02", "P04"] if unique else ["P02"]
        if delivery and billing:
            eligible += ["P03", "P05"] if unique else ["P03"]
        return {
            "candidate_id": f"candidate-{len(order_id)}-{hashlib.sha256(order_id.encode()).hexdigest()[:12]}",
            "sales_order": dict(order),
            "deliveries": delivery,
            "billings": billing,
            "d3_unique_search": unique,
            "eligible_tasks": eligible,
            "warnings": [],
        }

    def _get_order(self, order_id: str) -> dict[str, Any]:
        binding = self._binding("get_sales_order")
        filters = [f"{self._field(binding, 'sales_order_id')} eq {escape_literal(order_id)}"]
        rows = self._collection(binding, filters, self._select(binding), 2)
        if len(rows) > 1:
            raise ValueError("Sales Order identifier is not unique")
        if not rows:
            raise ValueError("Sales Order disappeared during candidate confirmation")
        return self._sales_order(rows[0], binding)

    def _search(self, criteria: Mapping[str, str], top: int) -> list[dict[str, Any]]:
        binding = self._binding("search_sales_orders")
        filters: list[str] = []
        if criteria.get("customer_id"):
            filters.append(f"{self._field(binding, 'customer_id')} eq {escape_literal(criteria['customer_id'])}")
        if criteria.get("order_date_from"):
            filters.append(f"{self._field(binding, 'order_date_from')} ge {date_literal(criteria['order_date_from'])}")
        if criteria.get("order_date_to"):
            filters.append(f"{self._field(binding, 'order_date_to')} le {date_literal(criteria['order_date_to'], end=True)}")
        if criteria.get("order_status"):
            code = self._code(binding["parameters"]["order_status"], criteria["order_status"])
            filters.append(f"{self._field(binding, 'order_status')} eq {escape_literal(code)}")
        rows = self._collection(binding, filters, self._select(binding), top)
        return [self._sales_order(row, binding) for row in rows]

    def _unique_search(self, order: Mapping[str, Any]) -> dict[str, Any] | None:
        customer, date, status = order.get("customer_id"), order.get("order_date"), order.get("order_status")
        options = [
            {"customer_id": customer, "order_date_from": date, "order_date_to": date, "order_status": status},
            {"customer_id": customer, "order_date_from": date, "order_date_to": date},
            {"order_date_from": date, "order_date_to": date, "order_status": status},
        ]
        for criteria in options:
            clean = {key: value for key, value in criteria.items() if value not in (None, "")}
            if not clean:
                continue
            rows = self._search(clean, 2)
            if len(rows) == 1 and rows[0].get("sales_order_id") == order.get("sales_order_id"):
                return {"criteria": clean, "matched_count": 1}
        return None

    def _related(self, operation_id: str, order_id: str, kind: str) -> list[dict[str, Any]]:
        binding = self._binding(operation_id)
        category = next((code for code, business in binding["discriminator"]["code_map"].items() if business == ("outbound_delivery" if kind == "delivery" else "billing_document")), None)
        if not category:
            raise ValueError(f"missing governed discriminator for {operation_id}")
        filters = [f"{self._field(binding, 'sales_order_id')} eq {escape_literal(order_id)}", f"{binding['discriminator']['property']} eq {escape_literal(category)}"]
        rows = self._collection(binding, filters, self._select(binding, include_discriminator=True), self.artifact["policy"]["maxRows"])
        id_field = "delivery_id" if kind == "delivery" else "billing_document_id"
        enrichment = binding.get("enrichment")
        if not enrichment:
            raise ValueError("missing governed enrichment")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            document_id = str(row.get(binding["output_fields"][id_field]["property"], "")).strip()
            if not document_id or document_id in seen:
                continue
            seen.add(document_id)
            enriched = self._enrich(operation_id, enrichment, document_id)
            fields = binding["output_fields"]
            item = {id_field: document_id, "sales_order_id": order_id}
            date_key = "delivery_date" if kind == "delivery" else "billing_date"
            status_key = "delivery_status" if kind == "delivery" else "billing_status"
            item[date_key] = normalized_date(enriched.get(fields[date_key]["property"]))
            item[status_key] = self._mapped(enriched.get(fields[status_key]["property"]), fields[status_key].get("code_map"))
            result.append(item)
        return result

    def _enrich(self, operation_id: str, enrichment: Mapping[str, Any], document_id: str) -> dict[str, Any]:
        fields = self._binding(operation_id)["output_fields"]
        selected = [enrichment["key_property"]] + [field["property"] for field in fields.values() if field.get("step_ref") == "enrichment"]
        params = {"$filter": f"{enrichment['key_property']} eq {escape_literal(document_id)}", "$select": ",".join(dict.fromkeys(selected)), "$top": "2", "$format": "json"}
        rows = self._collection_by_service(enrichment["service_id"], enrichment["entity_set"], params, 2)
        if len(rows) > 1:
            raise ValueError("enrichment result is not unique")
        return rows[0] if rows else {}

    def _collection(self, binding: Mapping[str, Any], filters: list[str], select: str, top: int) -> list[dict[str, Any]]:
        params = {"$select": select, "$top": str(min(top, self.artifact["policy"]["maxRows"])), "$format": "json"}
        if filters:
            params["$filter"] = " and ".join(filters)
        return self._collection_by_service(binding["service_id"], binding["entity_set"], params, top)

    def _collection_by_service(self, service_id: str, entity_set: str, params: Mapping[str, str], top: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        current = self._request(service_id, entity_set, params)
        while True:
            data = current.get("d")
            if not isinstance(data, Mapping) or not isinstance(data.get("results"), list):
                raise ValueError("SAP OData V2 collection shape is invalid")
            rows.extend(item for item in data["results"] if isinstance(item, Mapping))
            if len(rows) >= top or not data.get("__next"):
                return rows[:top]
            current = self._request_next(service_id, str(data["__next"]))

    def _request(self, service_id: str, entity_set: str, params: Mapping[str, str]) -> dict[str, Any]:
        self._pause()
        self.request_count += 1
        for attempt in range(self.max_retries + 1):
            try:
                return self.transport.get_json(service_id, entity_set, params)
            except Exception as exc:
                if attempt >= self.max_retries or not getattr(exc, "retryable", False):
                    raise
                time.sleep(min(1.0 * (attempt + 1), 2.0))
        raise AssertionError("unreachable")

    def _request_next(self, service_id: str, next_url: str) -> dict[str, Any]:
        self._pause()
        self.request_count += 1
        return self.transport.get_next_json(service_id, next_url)

    def _pause(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    def _binding(self, operation_id: str) -> Mapping[str, Any]:
        return self.artifact["operations"][operation_id]["binding"]

    @staticmethod
    def _field(binding: Mapping[str, Any], name: str) -> str:
        field = binding.get("parameters", {}).get(name) or binding.get("output_fields", {}).get(name)
        if not field or not field.get("property"):
            raise ValueError(f"governed field missing: {name}")
        return field["property"]

    @staticmethod
    def _select(binding: Mapping[str, Any], include_discriminator: bool = False) -> str:
        fields = [field["property"] for field in binding["output_fields"].values() if field.get("step_ref") != "enrichment"]
        if include_discriminator:
            fields.append(binding["discriminator"]["property"])
        return ",".join(dict.fromkeys(fields))

    @staticmethod
    def _code(field: Mapping[str, Any], business_value: str) -> str:
        for code, business in field.get("code_map", {}).items():
            if business == business_value:
                return code
        raise ValueError(f"unmapped governed status: {business_value}")

    @staticmethod
    def _mapped(value: Any, mapping: Mapping[str, str] | None) -> str | None:
        if value is None or value == "":
            return (mapping or {}).get("", "not_relevant")
        return (mapping or {}).get(str(value))

    def _sales_order(self, row: Mapping[str, Any], binding: Mapping[str, Any]) -> dict[str, Any]:
        fields = binding["output_fields"]
        order_id = str(row.get(fields["sales_order_id"]["property"], "")).strip()
        if not order_id:
            raise ValueError("Sales Order response lacks its identifier")
        return {
            "sales_order_id": order_id,
            "customer_id": None if row.get(fields["customer_id"]["property"]) is None else str(row.get(fields["customer_id"]["property"])),
            "order_date": normalized_date(row.get(fields["order_date"]["property"])),
            "order_status": self._mapped(row.get(fields["order_status"]["property"]), fields["order_status"].get("code_map")),
        }

    @staticmethod
    def _rank_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
        order = candidate["sales_order"]
        return (-(bool(candidate["deliveries"]) + bool(candidate["billings"])), -(order.get("order_status") == "completed"), order.get("order_date") or "", order.get("sales_order_id") or "")

    @staticmethod
    def _assign(candidates: list[Mapping[str, Any]]) -> dict[str, str | None]:
        assignment: dict[str, str | None] = {task: None for task in ("P01", "P02", "P03", "P04", "P05")}
        used: set[str] = set()
        for task in ("P05", "P03", "P04", "P02", "P01"):
            for candidate in candidates:
                cid = str(candidate["candidate_id"])
                if cid not in used and task in candidate.get("eligible_tasks", []):
                    assignment[task] = cid
                    used.add(cid)
                    break
        return assignment

    @staticmethod
    def _safe_error(exc: Exception) -> dict[str, Any]:
        return {"type": type(exc).__name__, "message": str(exc)[:240], "retryable": bool(getattr(exc, "retryable", False))}


def build_gateway_from_env(env_path: Path, artifact: Mapping[str, Any]) -> SapGatewayTransport:
    env = read_env(env_path)
    selectors = {service_id: service["runtime_selector"] for service_id, service in artifact["services"].items()}
    required = ["SAP_USER", "SAP_PASSWORD", "SAP_ODATA_CA_CERT", "SAP_ODATA_CERT_SHA256", *selectors.values()]
    missing = sorted({key for key in required if not env.get(key, "").strip()})
    if missing:
        raise RuntimeError("missing local gateway settings: " + ", ".join(missing))
    services = {service_id: service_root(env[key], key) for service_id, key in selectors.items()}
    return SapGatewayTransport(services, env["SAP_USER"], env["SAP_PASSWORD"], env.get("SAP_CLIENT", ""), env.get("SAP_LANGUAGE", ""), Path(env["SAP_ODATA_CA_CERT"]).expanduser().resolve(), env["SAP_ODATA_CERT_SHA256"].replace(":", "").replace(" ", "").lower())
