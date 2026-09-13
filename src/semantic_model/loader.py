"""Safe readers for governed model and sanitized evidence documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .errors import ModelLoadError


def _require_mapping(value: Any, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelLoadError(f"{path} must contain a mapping at its root")
    return value


def load_model(path: str | Path) -> dict[str, Any]:
    model_path = Path(path)
    try:
        payload = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ModelLoadError(f"cannot load semantic model {model_path}: {exc}") from exc
    return _require_mapping(payload, model_path)


def load_evidence(path: str | Path) -> dict[str, Any]:
    evidence_path = Path(path)
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"cannot load source evidence {evidence_path}: {exc}") from exc
    return _require_mapping(payload, evidence_path)


def load_json_schema(path: str | Path) -> dict[str, Any]:
    schema_path = Path(path)
    try:
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelLoadError(f"cannot load model schema {schema_path}: {exc}") from exc
    return _require_mapping(payload, schema_path)

