"""Small, deterministic Phase 07 logging and scoring core."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

OPERATIONS = {
    "search_sales_orders",
    "get_sales_order",
    "get_related_deliveries",
    "get_related_billing_documents",
}
ERROR_CATEGORIES = {
    "tool_selection_error",
    "parameter_error",
    "sap_query_error",
    "answer_synthesis_error",
    "tool_budget_exhausted",
}
IDENTIFIER_KEYS = {
    "SalesOrder",
    "SoldToParty",
    "sales_order_id",
    "customer_id",
    "delivery_id",
    "billing_document_id",
    "selected_order_id",
    "sales_orders",
    "deliveries",
    "billings",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def coded_value(value: Any, key: bytes) -> str:
    if isinstance(value, str) and value.startswith("hmac-sha256:"):
        return value
    return "hmac-sha256:" + hmac.new(key, canonical_bytes(value), hashlib.sha256).hexdigest()


def pseudonymize(value: Any, key: bytes, field: str | None = None) -> Any:
    """Code business identifiers while retaining task-relevant dates and statuses."""
    if field in IDENTIFIER_KEYS:
        if isinstance(value, list):
            return [coded_value(item, key) for item in value]
        if value is None:
            return None
        return coded_value(value, key)
    if isinstance(value, Mapping):
        return {name: pseudonymize(item, key, str(name)) for name, item in value.items()}
    if isinstance(value, list):
        return [pseudonymize(item, key, field) for item in value]
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_ground_truth(document: Mapping[str, Any], *, require_approved: bool = True) -> None:
    _require(document.get("schema_version") == "1.0", "ground truth schema_version must be 1.0")
    _require(isinstance(document.get("corpus_id"), str) and bool(document["corpus_id"]), "corpus_id is required")
    review_protocol = document.get("review_protocol", "human_plus_llm")
    _require(review_protocol in {"human_only", "human_plus_llm"}, "invalid review_protocol")
    cases = document.get("cases")
    _require(isinstance(cases, list) and bool(cases), "ground truth cases must be a non-empty list")
    seen: set[str] = set()
    for case in cases:
        _require(isinstance(case, Mapping), "each ground truth case must be an object")
        task_id = case.get("task_id")
        _require(isinstance(task_id, str) and task_id not in seen, "task_id must be unique")
        seen.add(task_id)
        _require(case.get("difficulty") in {"D1", "D2", "D3"}, f"invalid difficulty for {task_id}")
        _require(isinstance(case.get("required_operations"), list) and bool(case["required_operations"]), f"required_operations missing for {task_id}")
        for expected in case["required_operations"]:
            _require(expected.get("operation_id") in OPERATIONS, f"unknown operation in {task_id}")
            _require(isinstance(expected.get("expected_parameters"), Mapping), f"expected_parameters missing in {task_id}")
        fields = case.get("task_relevant_parameters")
        _require(isinstance(fields, list) and all(isinstance(item, str) for item in fields), f"task_relevant_parameters missing in {task_id}")
        _require(isinstance(case.get("expected_outcome"), Mapping), f"expected_outcome missing in {task_id}")
        review = case.get("review", {})
        if require_approved:
            _require(case.get("status") == "approved", f"ground truth case {task_id} is not approved")
            _require(bool(review.get("human_confirmation", {}).get("confirmed_at")), f"human confirmation missing in {task_id}")
            if review_protocol == "human_only":
                approval = review.get("human_approval", {})
                _require(bool(approval.get("approved_at")) and bool(approval.get("researcher")), f"human approval missing in {task_id}")
            else:
                llm = review.get("llm_review", {})
                _require(llm.get("verdict") in {"agree", "disagree"}, f"LLM review missing in {task_id}")
                _require(bool(llm.get("model")) and bool(llm.get("packet_sha256")), f"LLM provenance missing in {task_id}")
                if llm.get("verdict") == "disagree":
                    _require(bool(review.get("researcher_resolution", {}).get("resolved_at")), f"LLM disagreement unresolved in {task_id}")


def validate_scoring_policy(policy: Mapping[str, Any]) -> None:
    _require(policy.get("schema_version") == "1.0", "scoring policy schema_version must be 1.0")
    _require(policy.get("duplicate_call_policy") in {"incorrect", "ignore"}, "invalid duplicate_call_policy")
    retries = policy.get("maximum_retries")
    _require(isinstance(retries, int) and retries >= 0, "maximum_retries must be a non-negative integer")
    optional = policy.get("allowed_optional_operations", {})
    _require(isinstance(optional, Mapping), "allowed_optional_operations must be an object")
    for difficulty, operations in optional.items():
        _require(difficulty in {"D1", "D2", "D3"}, "invalid optional-operation difficulty")
        _require(isinstance(operations, list) and set(operations) <= OPERATIONS, "invalid optional operation")


class ExperimentLogWriter:
    """Append one sanitized JSON event per line for a single experiment run."""

    def __init__(self, path: Path, run_manifest: Mapping[str, Any], hmac_key: str):
        _require(len(hmac_key.encode("utf-8")) >= 32, "HMAC key must contain at least 32 bytes")
        self.path = path
        self.manifest = dict(run_manifest)
        self.key = hmac_key.encode("utf-8")
        self.lock = threading.Lock()
        self.last_sequence = 0
        self.closed = False
        path.parent.mkdir(parents=True, exist_ok=True)
        _require(not path.exists(), f"run log already exists: {path}")

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock:
            _require(not self.closed, "run is closed")
            sequence = event.get("sequence")
            _require(isinstance(sequence, int) and sequence == self.last_sequence + 1, "event sequence is not contiguous")
            _require(event.get("run_id") == self.manifest.get("run_id"), "event run_id mismatch")
            _require(event.get("task_id") == self.manifest.get("task_id"), "event task_id mismatch")
            _require(event.get("condition") == self.manifest.get("condition"), "event condition mismatch")
            _require(event.get("event_type") in {"run_started", "tool_call", "run_completed", "intervention", "run_invalid"}, "unsupported event_type")
            stored = pseudonymize(deepcopy(dict(event)), self.key)
            if stored["event_type"] == "run_started":
                stored["run_context"] = pseudonymize({
                    name: self.manifest.get(name)
                    for name in (
                        "transport",
                        "agent",
                        "model",
                        "catalog_sha256",
                        "runtime_sha256",
                        "ground_truth_sha256",
                        "scoring_policy_sha256",
                        "source_evidence_ids",
                    )
                }, self.key)
            stored["received_at"] = utc_now()
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(canonical_bytes(stored).decode("utf-8") + "\n")
                stream.flush()
            self.last_sequence = sequence
            if stored["event_type"] == "run_completed":
                self.closed = True
            return stored


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    _require(bool(events), "execution log is empty")
    for index, event in enumerate(events, 1):
        _require(event.get("sequence") == index, "execution log sequence is invalid")
    _require(events[0].get("event_type") == "run_started", "execution log must start with run_started")
    identity = {field: events[0].get(field) for field in ("run_id", "task_id", "condition", "repetition")}
    for event in events:
        _require(all(event.get(field) == value for field, value in identity.items()), "execution log identity changed within the run")
    _require(sum(event.get("event_type") == "run_started" for event in events) == 1, "execution log contains multiple run_started events")
    _require(sum(event.get("event_type") == "run_completed" for event in events) <= 1, "execution log contains multiple run_completed events")
    completed_positions = [index for index, event in enumerate(events) if event.get("event_type") == "run_completed"]
    if completed_positions:
        _require(completed_positions[0] == len(events) - 1, "execution log contains events after run_completed")
    invalid_events = [event for event in events if event.get("event_type") == "run_invalid"]
    for event in invalid_events:
        _require(event.get("invalid") is True, "run_invalid event must set invalid=true")
        _require(isinstance(event.get("reason"), str) and event.get("reason"), "run_invalid reason is required")
    return events


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, path))
        return result
    return {prefix: value}


def _outcome_contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and all(key in actual and _outcome_contains(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(item in actual for item in expected)
    return actual == expected


def score_run(events: list[Mapping[str, Any]], case: Mapping[str, Any], policy: Mapping[str, Any], reported_outcome: Mapping[str, Any]) -> dict[str, Any]:
    validate_scoring_policy(policy)
    calls = [event for event in events if event.get("event_type") == "tool_call" and event.get("actor") == "agent"]
    expected = [deepcopy(item) for item in case["required_operations"]]
    optional = set(policy.get("allowed_optional_operations", {}).get(case["difficulty"], []))
    attempts = [0 for _ in expected]
    retryable_failure = [False for _ in expected]
    correct_decisions = 0
    scored_decisions = 0
    parameter_correct = 0
    parameter_total = 0
    errors: list[str] = []
    matched_successes: set[int] = set()

    for call in calls:
        operation = call.get("canonical_operation")
        match = next((index for index, item in enumerate(expected) if index not in matched_successes and item["operation_id"] == operation), None)
        if match is not None:
            is_first = attempts[match] == 0
            is_allowed_retry = retryable_failure[match] and attempts[match] <= policy["maximum_retries"]
            allowed_decision = is_first or is_allowed_retry
            attempts[match] += 1
            scored_decisions += 1
            if allowed_decision:
                correct_decisions += 1
            else:
                errors.append("tool_selection_error")
            actual_fields = _flatten(call.get("parameters", {}))
            expected_fields = _flatten(expected[match].get("expected_parameters", {}))
            for field in case["task_relevant_parameters"]:
                if field in expected_fields:
                    parameter_total += 1
                    if actual_fields.get(field) == expected_fields[field]:
                        parameter_correct += 1
                    else:
                        errors.append("parameter_error")
            if call.get("success") is True and all(actual_fields.get(field) == expected_fields[field] for field in case["task_relevant_parameters"] if field in expected_fields):
                matched_successes.add(match)
            retryable_failure[match] = call.get("success") is False and bool((call.get("error") or {}).get("retryable"))
        elif operation in optional:
            correct_decisions += 1
            scored_decisions += 1
        else:
            if policy["duplicate_call_policy"] == "incorrect":
                scored_decisions += 1
                errors.append("tool_selection_error")
        if call.get("error_category") == "sap_query_error":
            errors.append("sap_query_error")
        elif call.get("error_category") == "parameter_error":
            errors.append("parameter_error")

    outcome_ok = _outcome_contains(reported_outcome, case["expected_outcome"])
    operations_complete = len(matched_successes) == len(expected)
    run_context = events[0].get("run_context", {}) if events else {}
    agent_context = run_context.get("agent", {}) if isinstance(run_context, Mapping) else {}
    call_limit = agent_context.get("tool_call_limit") if isinstance(agent_context, Mapping) else None
    over_limit = isinstance(call_limit, int) and len(calls) > call_limit
    task_success = operations_complete and outcome_ok and not over_limit
    if over_limit:
        errors.append("tool_selection_error")
    if operations_complete and not outcome_ok:
        errors.append("answer_synthesis_error")
    selection = correct_decisions / scored_decisions if scored_decisions else 0.0
    parameter = parameter_correct / parameter_total if parameter_total else 0.0
    return {
        "task_id": case["task_id"],
        "tool_selection_accuracy": selection,
        "parameter_accuracy": parameter,
        "task_success": int(task_success),
        "tool_call_limit_exceeded": over_limit,
        "tool_decisions": scored_decisions,
        "scored_parameters": parameter_total,
        "tool_selection_correct": correct_decisions,
        "parameter_correct": parameter_correct,
        "task_successes": int(task_success),
        "error_categories": sorted(set(errors)),
    }
