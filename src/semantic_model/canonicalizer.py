"""Deterministic canonical representation and hash for semantic models."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


_NON_SEMANTIC_KEYS = frozenset({"model_hash", "generated_at", "validated_at"})


def _strip_generated(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_generated(child)
            for key, child in value.items()
            if key not in _NON_SEMANTIC_KEYS
        }
    if isinstance(value, list):
        return [_strip_generated(child) for child in value]
    return value


def canonical_model_bytes(model: dict[str, Any]) -> bytes:
    normalized = _strip_generated(deepcopy(model))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def model_sha256(model: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_model_bytes(model)).hexdigest()

