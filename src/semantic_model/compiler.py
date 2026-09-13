"""Deterministic compiler for the validated C Semantic WebMCP catalog."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


COMPILER_VERSION = "0.1.0"
ARTIFACT_SCHEMA_VERSION = "1.0"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _model_hash(model: Mapping[str, Any]) -> str:
    from .canonicalizer import model_sha256

    return model_sha256(dict(model))


def _description(model: Mapping[str, Any], operation: Mapping[str, Any]) -> str:
    entities = model.get("entities", {})
    relationships = model.get("relationships", {})
    entity_parts = []
    for entity_id in operation.get("entity_refs", []):
        entity = entities[entity_id]
        entity_parts.append(f"{entity['business_name']}：{entity['description']}")
    relationship_parts = [
        relationships[relationship_id]["description"]
        for relationship_id in operation.get("relationship_refs", [])
    ]
    parts = [operation["purpose"]]
    if entity_parts:
        parts.append("涉及企業概念：" + "；".join(entity_parts))
    if relationship_parts:
        parts.append("業務關係：" + "；".join(relationship_parts))
    parts.append("唯讀政策：僅允許 HTTP GET，不修改 SAP 資料，且禁止使用 fallback。")
    return " ".join(parts)


def _referenced_defs(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        reference = schema.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            names.add(reference.removeprefix("#/$defs/"))
        for child in schema.values():
            names.update(_referenced_defs(child))
    elif isinstance(schema, list):
        for child in schema:
            names.update(_referenced_defs(child))
    return names


def _standalone_output_schema(model: Mapping[str, Any], schema_ref: str) -> dict[str, Any]:
    output_schemas = model["output_schemas"]
    schema = deepcopy(output_schemas[schema_ref])
    definitions = output_schemas.get("$defs", {})
    selected: dict[str, Any] = {}
    pending = list(_referenced_defs(schema))
    while pending:
        definition_id = pending.pop()
        if definition_id in selected:
            continue
        if definition_id not in definitions:
            raise ValueError(f"output schema references unknown definition {definition_id!r}")
        definition = deepcopy(definitions[definition_id])
        selected[definition_id] = definition
        pending.extend(_referenced_defs(definition) - selected.keys())
    if selected:
        schema["$defs"] = {key: selected[key] for key in sorted(selected)}
    return schema


def compile_catalog(model: Mapping[str, Any], *, compiler_version: str = COMPILER_VERSION) -> dict[str, Any]:
    """Compile a validated model into a deterministic, public C tool catalog."""

    if model.get("model", {}).get("status") != "validated":
        raise ValueError("only a validated model may be compiled")
    policies = model.get("policies", {})
    if policies.get("allowed_http_methods") != ["GET"] or policies.get("fallback") != "forbidden":
        raise ValueError("compiler requires the governed GET-only, no-fallback policy")

    operations = model["operations"]
    tools = []
    for operation_id in sorted(operations):
        operation = operations[operation_id]
        tools.append(
            {
                "operationId": operation_id,
                "name": operation_id,
                "description": _description(model, operation),
                "inputSchema": deepcopy(operation["input_schema"]),
                "annotations": {"readOnlyHint": True},
                "outputSchema": _standalone_output_schema(model, operation["output_schema_ref"]),
            }
        )

    model_info = model["model"]
    artifact: dict[str, Any] = {
        "schemaVersion": ARTIFACT_SCHEMA_VERSION,
        "condition": "C",
        "compilerVersion": compiler_version,
        "model": {
            "id": model_info["id"],
            "version": model_info["version"],
            "sha256": _model_hash(model),
            "sourceId": model_info["source_id"],
            "modelSourceId": model_info["model_source_id"],
        },
        "tools": tools,
    }
    artifact["artifactSha256"] = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    return artifact


def artifact_bytes(artifact: Mapping[str, Any]) -> bytes:
    """Return the stable serialized representation used for artifact files."""

    return json.dumps(
        artifact,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ).encode("utf-8") + b"\n"


def verify_artifact_hash(artifact: Mapping[str, Any]) -> bool:
    expected = artifact.get("artifactSha256")
    if not isinstance(expected, str):
        return False
    unsigned = {key: value for key, value in artifact.items() if key != "artifactSha256"}
    actual = hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()
    return actual == expected
