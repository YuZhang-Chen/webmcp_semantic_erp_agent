"""Deterministic private browser-runtime bindings for Phase 06."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Mapping

from .compiler import _canonical_bytes, _standalone_output_schema

RUNTIME_COMPILER_VERSION = "0.1.0"
RUNTIME_ARTIFACT_SCHEMA_VERSION = "1.0"


def compile_runtime_bindings(model: Mapping[str, Any], *, compiler_version: str = RUNTIME_COMPILER_VERSION) -> dict[str, Any]:
    """Compile validated model bindings without exposing credentials or endpoints."""

    if model.get("model", {}).get("status") != "validated":
        raise ValueError("only a validated model may produce runtime bindings")
    if model.get("model", {}).get("protocol") != "odata-v2":
        raise ValueError("runtime bindings require odata-v2")
    if model.get("policies", {}).get("allowed_http_methods") != ["GET"]:
        raise ValueError("runtime bindings require GET-only policy")
    services = model.get("runtime_services")
    if not isinstance(services, Mapping):
        raise ValueError("runtime_services are required")

    operations: dict[str, Any] = {}
    for operation_id in sorted(model.get("operations", {})):
        operation = model["operations"][operation_id]
        binding = deepcopy(model["bindings"][operation["binding_ref"]])
        service_id = binding.get("service_id")
        if service_id not in services:
            raise ValueError(f"unknown runtime service {service_id!r}")
        enrichment = binding.get("enrichment")
        if enrichment is not None and enrichment.get("service_id") not in services:
            raise ValueError(f"unknown enrichment runtime service {enrichment.get('service_id')!r}")
        operations[operation_id] = {
            "inputSchema": deepcopy(operation["input_schema"]),
            "outputSchema": _standalone_output_schema(model, operation["output_schema_ref"]),
            "bindingRef": operation["binding_ref"],
            "binding": binding,
        }

    model_info = model["model"]
    artifact: dict[str, Any] = {
        "schemaVersion": RUNTIME_ARTIFACT_SCHEMA_VERSION,
        "compilerVersion": compiler_version,
        "model": {
            "id": model_info["id"],
            "version": model_info["version"],
            "sha256": _model_hash(model),
            "sourceId": model_info["source_id"],
            "modelSourceId": model_info["model_source_id"],
        },
        "protocol": "odata-v2",
        "policy": {"allowedHttpMethods": ["GET"], "fallback": "forbidden", "maxRows": 50},
        "services": deepcopy(dict(services)),
        "operations": operations,
    }
    artifact["artifactSha256"] = hashlib.sha256(_canonical_bytes(artifact)).hexdigest()
    return artifact


def _model_hash(model: Mapping[str, Any]) -> str:
    from .canonicalizer import model_sha256

    return model_sha256(dict(model))


def runtime_artifact_bytes(artifact: Mapping[str, Any]) -> bytes:
    import json

    return json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
