import json
from collections import Counter
from pathlib import Path

import pytest

from experiment.budget_study import (
    BUDGET_BY_DIFFICULTY,
    BUDGET_TASKS,
    build_manifest,
    build_plan,
    build_schedule,
    derive_corpus,
    score_budget_run,
    sha256_value,
    validate_schedule,
    verify_manifest,
)
from experiment.phase07 import validate_scoring_policy


ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "experiment/private/phase08/formal-ground-truth-raw-human-confirmed-v1.json"
SEALED_PATH = ROOT / "experiment/private/phase08/formal-ground-truth-sealed-approved-v1.json"
POLICY_PATH = ROOT / "experiment/scoring-policy.json"
BUDGET_POLICY_PATH = ROOT / "experiment/phase08-budget-scoring-policy.json"


def _parents_and_attestation():
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    sealed = json.loads(SEALED_PATH.read_text(encoding="utf-8"))
    task_ids = [task for task, _ in BUDGET_TASKS]
    attestation = {
        "source_id": "webmcp.sap_sd.odata",
        "researcher": "test-researcher",
        "confirmed_at": "2026-09-16T00:00:00Z",
        "status": "confirmed",
        "task_ids": task_ids,
    }
    return raw, sealed, attestation


def test_derive_corpus_preserves_approved_pair_and_quota():
    raw_parent, sealed_parent, attestation = _parents_and_attestation()
    raw, sealed = derive_corpus(raw_parent, sealed_parent, candidate_hashes={"candidate.json": "abc"}, freshness_attestation=attestation)
    assert [case["task_id"] for case in raw["cases"]] == [f"CB08-T{i:02d}" for i in range(1, 13)]
    assert raw["derived_from"]["parent_corpus_sha256"]["sealed"] == sha256_value(sealed_parent)
    assert raw["derived_from"]["candidate_file_sha256"] == {"candidate.json": "abc"}
    assert Counter(case["difficulty"] for case in sealed["cases"]) == {"D1": 3, "D2": 4, "D3": 5}
    assert all(case["source_task_id"] for case in raw["cases"])


def test_schedule_is_deterministic_and_balanced():
    first, second = build_schedule(), build_schedule()
    assert first == second
    assert validate_schedule(first)["run_count"] == 72
    assert Counter(item["condition"] for item in first) == {"A": 24, "B": 24, "C": 24}


def test_plan_and_manifests_lock_task_budget():
    raw_parent, sealed_parent, attestation = _parents_and_attestation()
    raw, sealed = derive_corpus(raw_parent, sealed_parent, candidate_hashes={}, freshness_attestation=attestation)
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    validate_scoring_policy(policy)
    plan = build_plan(raw, sealed, policy_sha256="policy-hash", candidate_hashes={}, freshness_attestation=attestation)
    for entry in plan["schedule"][:12]:
        manifest = build_manifest(plan, entry)
        assert manifest["agent"]["tool_call_limit"] == BUDGET_BY_DIFFICULTY[plan["task_difficulty"][entry["task_id"]]]
        verify_manifest(manifest, plan)
    tampered = build_manifest(plan, plan["schedule"][0])
    tampered["agent"]["tool_call_limit"] = 99
    with pytest.raises(ValueError, match="tool_call_limit"):
        verify_manifest(tampered, plan)


def test_budget_policy_has_no_optional_operations():
    policy = json.loads(BUDGET_POLICY_PATH.read_text(encoding="utf-8"))
    validate_scoring_policy(policy)
    assert all(policy["allowed_optional_operations"][difficulty] == [] for difficulty in ("D1", "D2", "D3"))


def _case(task_id="CB08-T01", difficulty="D1"):
    return {
        "task_id": task_id,
        "difficulty": difficulty,
        "required_operations": [{"operation_id": "get_sales_order", "expected_parameters": {"sales_order_id": "SO-1"}}],
        "task_relevant_parameters": ["sales_order_id"],
        "expected_outcome": {"sales_orders": ["SO-1"], "deliveries": [], "billings": []},
    }


def _call(operation, parameters, success=True, executed=True, error_category=None):
    return {
        "event_type": "tool_call", "actor": "agent", "canonical_operation": operation,
        "parameters": parameters, "success": success, "executed": executed,
        "error_category": error_category, "error": None,
    }


def test_scoring_distinguishes_exhausted_attempt_from_executed_call():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    case = _case()
    events = [
        {"event_type": "run_started", "run_context": {"agent": {"tool_call_limit": 1}}},
        _call("get_sales_order", {"sales_order_id": "SO-1"}),
        _call("get_sales_order", {"sales_order_id": "SO-1"}, success=False, executed=False, error_category="tool_budget_exhausted"),
        {"event_type": "run_completed", "termination_reason": "tool_call_limit_exceeded"},
    ]
    result = score_budget_run(events, case, policy, {"sales_orders": ["SO-1"], "deliveries": [], "billings": []})
    assert result["budget_exhausted"] == 1
    assert result["task_success_under_budget"] == 0
    assert result["executed_tool_calls"] == 1
    assert result["attempted_tool_calls"] == 2
    assert "tool_budget_exhausted" in result["error_categories"]


def test_first_choice_rules_for_d2_and_d3():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    d2 = _case("CB08-T04", "D2")
    d2["required_operations"] = [
        {"operation_id": "get_related_deliveries", "expected_parameters": {"sales_order_id": "SO-1"}},
        {"operation_id": "get_related_billing_documents", "expected_parameters": {"sales_order_id": "SO-1"}},
    ]
    d2["task_relevant_parameters"] = ["sales_order_id"]
    d2["expected_outcome"] = {"sales_orders": [], "deliveries": [], "billings": []}
    events = [{"event_type": "run_started", "run_context": {"agent": {"tool_call_limit": 2}}}, _call("get_related_billing_documents", {"sales_order_id": "SO-1"}), {"event_type": "run_completed", "termination_reason": "agent_final_answer"}]
    assert score_budget_run(events, d2, policy, d2["expected_outcome"])["first_choice_accuracy"] == 1
    d3 = _case("CB08-T05", "D3")
    d3["required_operations"] = [{"operation_id": "search_sales_orders", "expected_parameters": {"criteria": {}}}]
    d3["task_relevant_parameters"] = []
    d3["expected_outcome"] = {"sales_orders": [], "deliveries": [], "billings": []}
    events[1] = _call("get_sales_order", {"sales_order_id": "SO-1"})
    assert score_budget_run(events, d3, policy, d3["expected_outcome"])["first_choice_accuracy"] == 0
