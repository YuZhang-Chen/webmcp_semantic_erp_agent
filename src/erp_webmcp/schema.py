from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any


class ModelValidationError(ValueError):
    """Raised when a semantic model violates the governed schema."""


ALLOWED_PARAMETER_TYPES = {"string", "integer", "number", "boolean"}
ALLOWED_PROTOCOLS = {"odata-v2", "odata-v4"}


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def content_sha256(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def load_model(path: str | Path) -> dict[str, Any]:
    model_path = Path(path)
    with model_path.open("r", encoding="utf-8") as stream:
        raw = json.load(stream)
    validate_model(raw)
    return raw


def _require_text(mapping: dict[str, Any], key: str, scope: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{scope}.{key} must be a non-empty string")
    return value.strip()


def _unique(items: list[dict[str, Any]], key: str, scope: str) -> set[str]:
    values: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ModelValidationError(f"{scope}[{index}] must be an object")
        values.append(_require_text(item, key, f"{scope}[{index}]"))
    if len(values) != len(set(values)):
        raise ModelValidationError(f"{scope}.{key} values must be unique")
    return set(values)


def validate_model(model: dict[str, Any]) -> None:
    if not isinstance(model, dict):
        raise ModelValidationError("model must be an object")
    for key in ("model_id", "model_version", "domain", "title"):
        _require_text(model, key, "model")

    policies = model.get("policies")
    if not isinstance(policies, dict):
        raise ModelValidationError("model.policies must be an object")
    if policies.get("sap_access") != "read_only":
        raise ModelValidationError("model.policies.sap_access must be read_only")
    if policies.get("allowed_methods") != ["GET"]:
        raise ModelValidationError("model.policies.allowed_methods must be exactly ['GET']")
    if int(policies.get("max_pages", 0)) < 1:
        raise ModelValidationError("model.policies.max_pages must be positive")

    entities = model.get("entities")
    relationships = model.get("relationships")
    services = model.get("services")
    operations = model.get("operations")
    if not isinstance(entities, list) or not entities:
        raise ModelValidationError("model.entities must be a non-empty array")
    if not isinstance(relationships, list):
        raise ModelValidationError("model.relationships must be an array")
    if not isinstance(services, dict) or not services:
        raise ModelValidationError("model.services must be a non-empty object")
    if not isinstance(operations, list) or not operations:
        raise ModelValidationError("model.operations must be a non-empty array")

    entity_ids = _unique(entities, "id", "model.entities")
    relationship_ids = _unique(relationships, "id", "model.relationships")
    operation_ids = _unique(operations, "id", "model.operations")

    for relation in relationships:
        if relation.get("from") not in entity_ids or relation.get("to") not in entity_ids:
            raise ModelValidationError(f"relationship {relation['id']} references an unknown entity")
        _require_text(relation, "business_description", f"relationship {relation['id']}")

    for service_id, service in services.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", service_id):
            raise ModelValidationError(f"invalid service id: {service_id}")
        if not isinstance(service, dict):
            raise ModelValidationError(f"service {service_id} must be an object")
        _require_text(service, "url_env", f"service {service_id}")
        protocol = _require_text(service, "default_protocol", f"service {service_id}")
        if protocol not in ALLOWED_PROTOCOLS:
            raise ModelValidationError(f"service {service_id} has unsupported protocol {protocol}")
        _require_text(service, "entity_set", f"service {service_id}")

    for operation in operations:
        operation_id = operation["id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", operation_id):
            raise ModelValidationError(f"invalid operation id: {operation_id}")
        if operation.get("entity") not in entity_ids:
            raise ModelValidationError(f"operation {operation_id} references an unknown entity")
        if operation.get("method") != "GET" or operation.get("read_only_policy") is not True:
            raise ModelValidationError(f"operation {operation_id} must be GET-only and read-only")
        _require_text(operation, "business_description", f"operation {operation_id}")
        _require_text(operation, "typed_description", f"operation {operation_id}")

        relation_refs = operation.get("relationship_ids", [])
        if not isinstance(relation_refs, list) or not set(relation_refs).issubset(relationship_ids):
            raise ModelValidationError(f"operation {operation_id} has an unknown relationship")

        binding = operation.get("odata_binding")
        if not isinstance(binding, dict):
            raise ModelValidationError(f"operation {operation_id}.odata_binding must be an object")
        service_id = binding.get("service")
        if service_id not in services:
            raise ModelValidationError(f"operation {operation_id} references unknown service {service_id}")
        if binding.get("method") != "GET":
            raise ModelValidationError(f"operation {operation_id} OData binding must use GET")

        parameters = operation.get("parameters")
        if not isinstance(parameters, list):
            raise ModelValidationError(f"operation {operation_id}.parameters must be an array")
        business_names = _unique(parameters, "name", f"operation {operation_id}.parameters")
        published_technical_names = [
            parameter.get("technical_parameter_name", parameter.get("technical_name"))
            for parameter in parameters
        ]
        if any(not isinstance(item, str) or not item for item in published_technical_names):
            raise ModelValidationError(
                f"operation {operation_id} parameters require technical names"
            )
        technical_names = set(published_technical_names)
        if len(technical_names) != len(published_technical_names):
            raise ModelValidationError(
                f"operation {operation_id} technical parameter names must be unique"
            )
        if not business_names or not technical_names:
            raise ModelValidationError(f"operation {operation_id} must declare parameters")
        for parameter in parameters:
            parameter_type = parameter.get("type")
            if parameter_type not in ALLOWED_PARAMETER_TYPES:
                raise ModelValidationError(
                    f"operation {operation_id} parameter {parameter['name']} has invalid type"
                )
            _require_text(parameter, "business_description", f"parameter {parameter['name']}")
            if parameter.get("pattern"):
                re.compile(str(parameter["pattern"]))
            if int(parameter.get("max_length", 1)) < 1:
                raise ModelValidationError(f"parameter {parameter['name']} max_length must be positive")

        output_schema = operation.get("output_schema")
        if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
            raise ModelValidationError(f"operation {operation_id}.output_schema must be an object schema")

    if len(operation_ids) != 4:
        raise ModelValidationError("the controlled study must expose exactly four operations")
