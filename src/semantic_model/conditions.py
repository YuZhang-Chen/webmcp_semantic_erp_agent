"""Deterministic A/B/C tool contracts for the Phase 05 prototype."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from .compiler import (
    COMPILER_VERSION,
    _canonical_bytes,
    _standalone_output_schema,
    compile_catalog,
    verify_artifact_hash,
)
from .canonicalizer import model_sha256


CONDITION_SUITE_VERSION = "0.1.0"
CONDITIONS = ("A", "B", "C")
CANONICAL_OPERATIONS = (
    "get_related_billing_documents",
    "get_related_deliveries",
    "get_sales_order",
    "search_sales_orders",
)

A_TOOL_NAMES = {
    "search_sales_orders": "query_A_SalesOrder",
    "get_sales_order": "read_A_SalesOrder",
    "get_related_deliveries": "query_A_SalesOrderItmSubsqntProcFlow_J",
    "get_related_billing_documents": "query_A_SalesOrderItmSubsqntProcFlow_M",
}

B_TOOL_DESCRIPTIONS = {
    "search_sales_orders": "依一項或多項支援條件搜尋銷售訂單。",
    "get_sales_order": "使用銷售訂單識別碼取得單筆銷售訂單。",
    "get_related_deliveries": "使用銷售訂單識別碼取得交貨資料。",
    "get_related_billing_documents": "使用銷售訂單識別碼取得請款文件資料。",
}

A_TOOL_DESCRIPTIONS = {
    "search_sales_orders": "對 EntitySet A_SalesOrder 執行 GET collection_filter 查詢。",
    "get_sales_order": "對 EntitySet A_SalesOrder 執行 GET unique_filter 查詢。",
    "get_related_deliveries": (
        "對 EntitySet A_SalesOrderItmSubsqntProcFlow 執行 GET collection_filter 查詢，"
        "並固定 SubsequentDocumentCategory=J。"
    ),
    "get_related_billing_documents": (
        "對 EntitySet A_SalesOrderItmSubsqntProcFlow 執行 GET collection_filter 查詢，"
        "並固定 SubsequentDocumentCategory=M。"
    ),
}


def _string_schema(*, description: str | None = None, min_length: int | None = None,
                   max_length: int | None = None, fmt: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if description is not None:
        schema["description"] = description
    if min_length is not None:
        schema["minLength"] = min_length
    if max_length is not None:
        schema["maxLength"] = max_length
    if fmt is not None:
        schema["format"] = fmt
    return schema


def _b_input_schema(operation_id: str) -> dict[str, Any]:
    if operation_id == "search_sales_orders":
        criteria = {
            "type": "object",
            "additionalProperties": False,
            "minProperties": 1,
            "properties": {
                "customer_id": _string_schema(
                    description="客戶識別碼。", min_length=1, max_length=10, fmt="sap_customer_id"
                ),
                "order_date_from": _string_schema(
                    description="訂單日期區間起點（含當日）。", fmt="date"
                ),
                "order_date_to": _string_schema(
                    description="訂單日期區間終點（含當日）。", fmt="date"
                ),
                "order_status": {
                    **_string_schema(description="銷售訂單狀態。", min_length=1),
                    "enum": ["not_started", "partially_completed", "completed"],
                },
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["criteria"],
            "properties": {"criteria": criteria},
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["sales_order_id"],
        "properties": {
            "sales_order_id": _string_schema(
                description="銷售訂單識別碼。", min_length=1, max_length=10, fmt="sap_sales_order_id"
            )
        },
    }


def _a_input_schema(operation_id: str) -> dict[str, Any]:
    if operation_id == "search_sales_orders":
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["filter"],
            "properties": {
                "filter": {
                    "type": "object",
                    "additionalProperties": False,
                    "minProperties": 1,
                    "properties": {
                        "SoldToParty": _string_schema(max_length=10),
                        "SalesOrderDate": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "ge": _string_schema(),
                                "le": _string_schema(),
                            },
                        },
                        "OverallSDProcessStatus": _string_schema(max_length=1),
                    },
                }
            },
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["SalesOrder"],
        "properties": {"SalesOrder": _string_schema(max_length=10)},
    }


def _neutral_b_description(operation_id: str) -> str:
    return B_TOOL_DESCRIPTIONS[operation_id]


def _build_artifact(model: Mapping[str, Any], condition: str) -> dict[str, Any]:
    if condition == "C":
        return compile_catalog(model)
    tools: list[dict[str, Any]] = []
    operations = model["operations"]
    for operation_id in CANONICAL_OPERATIONS:
        operation = operations[operation_id]
        tools.append(
            {
                "operationId": operation_id,
                "name": A_TOOL_NAMES[operation_id] if condition == "A" else operation_id,
                "description": (
                    A_TOOL_DESCRIPTIONS[operation_id]
                    if condition == "A"
                    else _neutral_b_description(operation_id)
                ),
                "inputSchema": (
                    _a_input_schema(operation_id)
                    if condition == "A"
                    else _b_input_schema(operation_id)
                ),
                "annotations": {"readOnlyHint": True},
                "outputSchema": _standalone_output_schema(model, operation["output_schema_ref"]),
            }
        )
    artifact: dict[str, Any] = {
        "schemaVersion": "1.0",
        "condition": condition,
        "compilerVersion": COMPILER_VERSION,
        "model": {
            "id": model["model"]["id"],
            "version": model["model"]["version"],
            "sha256": model_sha256(dict(model)),
            "sourceId": model["model"]["source_id"],
            "modelSourceId": model["model"]["model_source_id"],
        },
        "tools": tools,
    }
    artifact["artifactSha256"] = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    return artifact


CANONICALIZATION = {
    "A": {
        "search_sales_orders": {
            "filter.SoldToParty": "criteria.customer_id",
            "filter.SalesOrderDate.ge": "criteria.order_date_from",
            "filter.SalesOrderDate.le": "criteria.order_date_to",
            "filter.OverallSDProcessStatus": "criteria.order_status",
            "statusMap": {"A": "not_started", "B": "partially_completed", "C": "completed"},
        },
        "get_sales_order": {"SalesOrder": "sales_order_id"},
        "get_related_deliveries": {"SalesOrder": "sales_order_id", "SubsequentDocumentCategory": "J"},
        "get_related_billing_documents": {"SalesOrder": "sales_order_id", "SubsequentDocumentCategory": "M"},
    },
    "B": {operation_id: "identity" for operation_id in CANONICAL_OPERATIONS},
    "C": {operation_id: "identity" for operation_id in CANONICAL_OPERATIONS},
}


def compile_condition_suite(model: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    catalogs = {condition: _build_artifact(model, condition) for condition in CONDITIONS}
    manifest: dict[str, Any] = {
        "schemaVersion": "1.0",
        "suiteVersion": CONDITION_SUITE_VERSION,
        "model": catalogs["C"]["model"],
        "conditions": {
            condition: {
                "artifactSha256": catalogs[condition]["artifactSha256"],
                "toolNames": {tool["operationId"]: tool["name"] for tool in catalogs[condition]["tools"]},
            }
            for condition in CONDITIONS
        },
        "canonicalization": deepcopy(CANONICALIZATION),
        "invariants": {
            "operationIds": list(CANONICAL_OPERATIONS),
            "sharedOutputSchemas": True,
            "sharedReadOnlyAnnotations": True,
            "sharedCanonicalExecution": True,
        },
    }
    manifest["suiteSha256"] = hashlib.sha256(_canonical_bytes(manifest)).hexdigest()
    return catalogs, manifest


def verify_condition_suite(catalogs: Mapping[str, Mapping[str, Any]], manifest: Mapping[str, Any]) -> bool:
    if set(catalogs) != set(CONDITIONS):
        return False
    if manifest.get("conditions", {}).keys() != set(CONDITIONS):
        return False
    expected_outputs = None
    for condition in CONDITIONS:
        catalog = catalogs[condition]
        if catalog.get("condition") != condition:
            return False
        if not verify_artifact_hash(catalog):
            return False
        if [tool.get("operationId") for tool in catalog.get("tools", [])] != list(CANONICAL_OPERATIONS):
            return False
        if catalog.get("artifactSha256") != manifest["conditions"][condition].get("artifactSha256"):
            return False
        outputs = [tool.get("outputSchema") for tool in catalog["tools"]]
        if expected_outputs is None:
            expected_outputs = outputs
        elif outputs != expected_outputs:
            return False
        if any(tool.get("annotations") != {"readOnlyHint": True} for tool in catalog["tools"]):
            return False
    return True


def artifact_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def canonicalize_arguments(condition: str, operation_id: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if operation_id not in CANONICAL_OPERATIONS:
        raise ValueError(f"unknown operation {operation_id!r}")
    if condition in {"B", "C"}:
        expected = {"criteria"} if operation_id == "search_sales_orders" else {"sales_order_id"}
        if set(arguments) != expected:
            raise ValueError(f"invalid {condition} arguments for {operation_id}")
        if operation_id == "search_sales_orders":
            allowed = {"customer_id", "order_date_from", "order_date_to", "order_status"}
            if not isinstance(arguments["criteria"], Mapping) or not set(arguments["criteria"]).issubset(allowed):
                raise ValueError("invalid criteria")
        return deepcopy(dict(arguments))
    if condition != "A":
        raise ValueError(f"unknown condition {condition!r}")
    if operation_id == "search_sales_orders":
        if set(arguments) != {"filter"} or not isinstance(arguments["filter"], Mapping):
            raise ValueError("filter is required and must be an object")
        source = arguments.get("filter", {})
        if not set(source).issubset({"SoldToParty", "SalesOrderDate", "OverallSDProcessStatus"}):
            raise ValueError("unknown technical filter")
        target: dict[str, Any] = {}
        if "SoldToParty" in source:
            target["customer_id"] = source["SoldToParty"]
        dates = source.get("SalesOrderDate", {})
        if "ge" in dates:
            target["order_date_from"] = dates["ge"]
        if "le" in dates:
            target["order_date_to"] = dates["le"]
        if "OverallSDProcessStatus" in source:
            try:
                target["order_status"] = {"A": "not_started", "B": "partially_completed", "C": "completed"}[source["OverallSDProcessStatus"]]
            except KeyError as exc:
                raise ValueError("unknown OverallSDProcessStatus") from exc
        return {"criteria": target}
    if set(arguments) != {"SalesOrder"}:
        raise ValueError("SalesOrder is required")
    return {"sales_order_id": arguments["SalesOrder"]}
