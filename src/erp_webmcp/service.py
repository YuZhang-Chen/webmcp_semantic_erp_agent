from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any, Callable

from .odata import ODataClient, ODataError, odata_literal
from .schema import load_model


ClientFactory = Callable[[str, str, int, float], ODataClient]


def _default_client_factory(url: str, protocol: str, max_pages: int, timeout: float) -> ODataClient:
    return ODataClient.from_environment(
        url, protocol, max_pages=max_pages, timeout_seconds=timeout
    )


class SemanticToolService:
    def __init__(self, model_path: str, client_factory: ClientFactory | None = None) -> None:
        self.model = load_model(model_path)
        self.operations = {item["id"]: item for item in self.model["operations"]}
        self.client_factory = client_factory or _default_client_factory

    def health(self) -> dict[str, Any]:
        services = {}
        for service_id, service in self.model["services"].items():
            services[service_id] = {
                "configured": bool(os.environ.get(service["url_env"])),
                "url_env": service["url_env"],
            }
        return {
            "status": "ok",
            "model_id": self.model["model_id"],
            "model_version": self.model["model_version"],
            "sap_access": "read_only",
            "protocol": os.environ.get("SAP_ODATA_PROTOCOL", "odata-v2"),
            "services": services,
        }

    def _validate_arguments(self, operation: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        specs = {item["name"]: item for item in operation["parameters"]}
        unknown = set(arguments) - set(specs)
        if unknown:
            raise ValueError(f"unknown arguments: {sorted(unknown)}")
        normalized: dict[str, Any] = {}
        for name, spec in specs.items():
            value = arguments.get(name)
            if value in (None, ""):
                if spec.get("required"):
                    raise ValueError(f"missing required argument: {name}")
                continue
            if spec["type"] == "string":
                value = str(value).strip()
                if len(value) > int(spec.get("max_length", 80)):
                    raise ValueError(f"argument {name} is too long")
                if spec.get("pattern") and not re.fullmatch(spec["pattern"], value):
                    raise ValueError(f"argument {name} has an invalid format")
            elif spec["type"] == "integer":
                value = int(value)
                if "minimum" in spec and value < spec["minimum"]:
                    raise ValueError(f"argument {name} is below minimum")
                if "maximum" in spec and value > spec["maximum"]:
                    raise ValueError(f"argument {name} is above maximum")
            normalized[name] = value
        if operation["id"] == "search_sales_orders" and not (
            set(normalized) - {"limit"}
        ):
            raise ValueError("search_sales_orders requires at least one business filter")
        return normalized

    def execute(self, operation_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        operation = self.operations.get(operation_id)
        if operation is None:
            raise KeyError(f"unknown operation: {operation_id}")
        normalized = self._validate_arguments(operation, arguments)
        binding = operation["odata_binding"]
        service = self.model["services"][binding["service"]]
        base_url = os.environ.get(service["url_env"], "")
        if not base_url:
            raise ODataError(f"SAP service is not configured; set {service['url_env']}")
        protocol = os.environ.get("SAP_ODATA_PROTOCOL", service["default_protocol"])
        if protocol not in {"odata-v2", "odata-v4"}:
            raise ODataError("SAP_ODATA_PROTOCOL must be odata-v2 or odata-v4")
        policies = self.model["policies"]
        client = self.client_factory(
            base_url,
            protocol,
            int(policies["max_pages"]),
            float(policies["timeout_seconds"]),
        )

        specs = {item["name"]: item for item in operation["parameters"]}
        filters: list[str] = []
        limit = int(normalized.get("limit", binding.get("default_top", 20)))
        for name, value in normalized.items():
            if name == "limit":
                continue
            spec = specs[name]
            operator = spec.get("operator", "eq")
            literal = odata_literal(
                value,
                spec.get("odata_type", spec["type"]),
                protocol,
                end_of_day=operator == "le" and spec.get("odata_type") == "date",
            )
            filters.append(f"{spec['technical_name']} {operator} {literal}")
        query = {
            "$select": ",".join(binding["select"]),
            "$top": str(limit),
        }
        if filters:
            query["$filter"] = " and ".join(filters)
        rows, request_id = client.get(service["entity_set"], query)
        return {
            "operation_id": operation_id,
            "model_id": self.model["model_id"],
            "model_version": self.model["model_version"],
            "protocol": protocol,
            "source_classification": "external live",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "request_id": request_id,
            "row_count": len(rows),
            "rows": rows,
        }
