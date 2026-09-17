from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.phase08_cli import main as phase08_cli
from experiment.phase08 import (
    FORMAL_QUOTA,
    PHASE08_SEED,
    build_manifest,
    build_plan,
    build_schedule,
    build_task_prompts,
    validate_phase08_corpus,
    validate_schedule,
    validate_timeout_gate,
    verify_manifest,
)


POLICY = {
    "schema_version": "1.0",
    "duplicate_call_policy": "incorrect",
    "maximum_retries": 1,
    "allowed_optional_operations": {"D1": [], "D2": ["get_sales_order"], "D3": ["get_sales_order"]},
}


def _case(task_id: str, difficulty: str, order: str) -> dict:
    operation = "get_sales_order" if difficulty == "D1" else "get_related_deliveries"
    return {
        "task_id": task_id,
        "difficulty": difficulty,
        "status": "approved",
        "required_operations": [{"operation_id": operation, "expected_parameters": {"sales_order_id": order}}],
        "task_relevant_parameters": ["sales_order_id"],
        "expected_outcome": {"sales_orders": []} if difficulty == "D1" else {"deliveries": []},
        "review": {
            "human_confirmation": {"researcher": "test", "confirmed_at": "2026-09-15T00:00:00Z"},
            "human_approval": {"researcher": "test", "approved_at": "2026-09-15T00:01:00Z", "protocol": "human_only"},
        },
    }


def _pilot() -> dict:
    return {"schema_version": "1.0", "corpus_id": "phase08-test", "review_protocol": "human_only", "cases": [
        _case("P01", "D1", "1001"), _case("P02", "D2", "1002"), _case("P03", "D2", "1003"),
        _case("P04", "D3", "1004"), _case("P05", "D3", "1005"),
    ]}


def test_phase08_schedules_are_deterministic_balanced_and_complete():
    pilot = build_schedule("pilot")
    formal = build_schedule("formal")
    assert pilot == build_schedule("pilot", seed=PHASE08_SEED)
    assert validate_schedule(pilot, "pilot")["run_count"] == 45
    assert validate_schedule(formal, "formal")["run_count"] == 180
    assert len({item["run_id"] for item in formal}) == 180


def test_phase08_pilot_plan_remaps_legacy_case_ids_without_changing_raw_prompt_source():
    corpus = _pilot()
    plan = build_plan(corpus, POLICY, mode="pilot", raw_corpus=corpus)
    assert plan["mode"] == "pilot"
    assert len(plan["schedule"]) == 45
    assert set(plan["tasks"]) == {f"P08-P{i:02d}" for i in range(1, 6)}
    assert "1001" in plan["tasks"]["P08-P01"]["text"]
    assert plan["agent"]["timeout_seconds"] == 120
    assert plan["agent"]["tool_call_limit"] == 8


def test_phase08_task_prompts_use_natural_business_language():
    d1 = _case("P01", "D1", "10569")
    d2 = _case("P02", "D2", "10588")
    d2["required_operations"].append({
        "operation_id": "get_related_billing_documents",
        "expected_parameters": {"sales_order_id": "10588"},
    })
    d3 = _case("P03", "D3", "10861")
    d3["required_operations"].insert(0, {
        "operation_id": "search_sales_orders",
        "expected_parameters": {"criteria": {
            "customer_id": "1000995",
            "order_date_from": "2026-03-04",
            "order_date_to": "2026-03-04",
            "order_status": "completed",
        }},
    })
    prompts = build_task_prompts({"cases": [d1, d2, d3]})
    combined = " ".join(item["text"] for item in prompts.values())
    assert "Sales Order" not in combined
    assert "get_sales_order" not in combined
    assert "get_related" not in combined
    assert "completed" not in combined
    assert "訂單資料" in prompts["P01"]["text"]
    assert "出貨與請款資料" in prompts["P02"]["text"]
    assert "客戶 1000995 在 2026 年 3 月 4 日已完成的訂單" in prompts["P03"]["text"]


def test_run_manifest_uses_the_scheduled_index():
    corpus = _pilot()
    plan = build_plan(corpus, POLICY, mode="pilot", raw_corpus=corpus)
    manifest = build_manifest(plan, plan["schedule"][0])
    verify_manifest(manifest, plan)
    manifest["schedule_index"] += 1
    with pytest.raises(ValueError, match="schedule_index"):
        verify_manifest(manifest, plan)


def test_formal_schedule_requires_fixed_quota():
    formal = build_schedule("formal")
    assert FORMAL_QUOTA == {"D1": 4, "D2": 8, "D3": 8}
    with pytest.raises(ValueError, match="formal schedule"):
        validate_schedule(formal[:-1], "formal")


def test_formal_raw_corpus_counts_one_order_per_task_with_two_downstream_operations():
    cases = []
    for index in range(1, 21):
        difficulty = "D1" if index <= 4 else "D2" if index <= 12 else "D3"
        order_id = str(1000 + index)
        case = _case(f"F08-T{index:02d}", difficulty, order_id)
        if difficulty == "D2":
            case["required_operations"].append({
                "operation_id": "get_related_billing_documents",
                "expected_parameters": {"sales_order_id": order_id},
            })
        if difficulty == "D3":
            case["required_operations"].insert(0, {
                "operation_id": "search_sales_orders",
                "expected_parameters": {"criteria": {"customer_id": f"C{index}"}},
            })
        cases.append(case)
    corpus = {
        "schema_version": "1.0",
        "corpus_id": "formal-test",
        "source_id": "webmcp.sap_sd.odata",
        "review_protocol": "human_only",
        "cases": cases,
    }
    assert validate_phase08_corpus(corpus, "formal", raw_corpus=corpus)["case_count"] == 20
    cases[-1]["required_operations"][-1]["expected_parameters"]["sales_order_id"] = "1019"
    with pytest.raises(ValueError, match="distinct Sales Order"):
        validate_phase08_corpus(corpus, "formal", raw_corpus=corpus)


def test_timeout_gate_requires_controlled_interrupted_turn():
    validate_timeout_gate({
        "browser_attachment_verified": True,
        "controlled_start": "2026-09-15T00:00:00Z",
        "timeout_seconds": 120,
        "interrupted_at": "2026-09-15T00:02:00Z",
        "turn_status": "interrupted",
    })
    with pytest.raises(ValueError, match="interrupted 120-second"):
        validate_timeout_gate({
            "browser_attachment_verified": True,
            "controlled_start": "2026-09-15T00:00:00Z",
            "timeout_seconds": 120,
            "interrupted_at": "2026-09-15T00:02:00Z",
            "turn_status": "completed",
        })


def test_timeout_gate_accepts_explicit_researcher_waiver():
    validate_timeout_gate({
        "status": "waived",
        "waived_by": "researcher-01",
        "waived_at": "2026-09-16T05:00:00Z",
        "reason": "Desktop task interruption control is unavailable in the current integration.",
        "acknowledged_limitations": True,
    })


def test_replacement_manifest_can_replace_a_failed_replacement(tmp_path: Path):
    corpus = _pilot()
    plan = build_plan(corpus, POLICY, mode="pilot", raw_corpus=corpus)
    plan_path = tmp_path / "plan.json"
    base_path = tmp_path / "base.json"
    first_path = tmp_path / "first-replacement.json"
    second_path = tmp_path / "second-replacement.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    base_path.write_text(json.dumps(build_manifest(plan, plan["schedule"][0])), encoding="utf-8")
    assert phase08_cli([
        "make-replacement-manifest", "--plan", str(plan_path), "--base-manifest", str(base_path),
        "--replacement-run-id", "replacement-1", "--output", str(first_path),
    ]) == 0
    assert phase08_cli([
        "make-replacement-manifest", "--plan", str(plan_path), "--base-manifest", str(first_path),
        "--replacement-run-id", "replacement-2", "--output", str(second_path),
    ]) == 0
    second = json.loads(second_path.read_text(encoding="utf-8"))
    assert second["replaces_run_id"] == plan["schedule"][0]["run_id"]
    assert second["attempt"] == 3
