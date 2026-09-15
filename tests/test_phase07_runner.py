from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.runner import build_pilot_plan, interleaved_schedule, parse_reported_outcome, project_id_only_case, validate_reported_outcome
from experiment.phase07 import ExperimentLogWriter, coded_value, load_jsonl, pseudonymize
from experiment.cli import main as experiment_cli


def corpus() -> dict:
    cases = []
    for task_id, operation, params in [
        ("P01", "get_sales_order", {"sales_order_id": "25"}),
        ("P02", "get_related_deliveries", {"sales_order_id": "24"}),
        ("P03", "get_related_deliveries", {"sales_order_id": "22"}),
        ("P04", "search_sales_orders", {"criteria": {"customer_id": "C", "order_date_from": "2020-01-01", "order_date_to": "2020-01-01", "order_status": "completed"}}),
        ("P05", "search_sales_orders", {"criteria": {"customer_id": "D", "order_date_from": "2020-01-02", "order_date_to": "2020-01-02", "order_status": "completed"}}),
    ]:
        cases.append({"task_id": task_id, "required_operations": [{"operation_id": operation, "expected_parameters": params}]})
    return {"cases": cases}


def test_schedule_is_15_runs_and_balanced():
    schedule = interleaved_schedule()
    assert len(schedule) == 15
    assert {(item["task_id"], item["condition"]) for item in schedule} == {(task, condition) for task in ("P01", "P02", "P03", "P04", "P05") for condition in ("A", "B", "C")}


def test_plan_uses_raw_prompt_source_and_fixed_answer_contract():
    plan = build_pilot_plan(corpus(), {"schema_version": "1.0", "maximum_retries": 1, "duplicate_call_policy": "incorrect"}, prompt_source=corpus())
    assert len(plan["schedule"]) == 15
    assert "25" in plan["tasks"]["P01"]["text"]
    assert set(plan["answer_schema"]["required"]) == {"sales_orders", "deliveries", "billings"}


def test_reported_outcome_is_strict_json(tmp_path: Path):
    path = tmp_path / "answer.json"
    path.write_text(json.dumps({"sales_orders": ["25"], "deliveries": [], "billings": []}), encoding="utf-8")
    assert parse_reported_outcome(path)["sales_orders"] == ["25"]
    with pytest.raises(ValueError):
        validate_reported_outcome({"sales_orders": [], "deliveries": []})
    path.write_text("Here is the answer: {}", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        parse_reported_outcome(path)


def test_close_run_archives_and_parses_raw_answer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = "phase07-runner-test-key-with-at-least-thirty-two-bytes"
    monkeypatch.setenv("HMAC_KEY", key)
    log = tmp_path / "P01-A-R1.jsonl"
    manifest = {"run_id": "P01-A-R1", "task_id": "P01", "condition": "A", "repetition": 1}
    writer = ExperimentLogWriter(log, manifest, key)
    writer.append({"sequence": 1, **manifest, "event_type": "run_started", "actor": "system"})
    answer = tmp_path / "answer.txt"
    answer.write_text('{"sales_orders":["25"],"deliveries":[],"billings":[]}', encoding="utf-8")
    assert experiment_cli(["close-run", "--log", str(log), "--answer-file", str(answer)]) == 0
    assert log.with_name("P01-A-R1.answer.raw").read_text(encoding="utf-8") == answer.read_text(encoding="utf-8")
    assert load_jsonl(log)[-1]["reported_outcome"]["sales_orders"][0].startswith("hmac-sha256:")


def test_id_only_projection_checks_approved_seal_before_scoring():
    key = "phase07-runner-test-key-with-at-least-thirty-two-bytes"
    raw = {
        "task_id": "P02", "candidate_id": "candidate-test",
        "required_operations": [{"operation_id": "get_related_deliveries", "expected_parameters": {"sales_order_id": "24"}}],
        "expected_outcome": {"deliveries": [{"delivery_id": "80000002", "delivery_status": "completed", "sales_order_id": "24"}]},
    }
    sealed = {
        **raw, "status": "approved",
        "required_operations": [{"operation_id": "get_related_deliveries", "expected_parameters": pseudonymize({"sales_order_id": "24"}, key.encode())}],
        "expected_outcome": {"deliveries": [coded_value(raw["expected_outcome"]["deliveries"][0], key.encode())]},
    }
    projected = project_id_only_case(raw, sealed, key)
    assert projected["expected_outcome"]["deliveries"] == [coded_value("80000002", key.encode())]
    broken = {**sealed, "expected_outcome": {"deliveries": ["hmac-sha256:wrong"]}}
    with pytest.raises(ValueError, match="approved sealed HMAC"):
        project_id_only_case(raw, broken, key)


def test_closed_raw_id_answer_scores_against_verified_projection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    key = "phase07-runner-test-key-with-at-least-thirty-two-bytes"
    monkeypatch.setenv("HMAC_KEY", key)
    raw_case = {
        "task_id": "P02", "candidate_id": "candidate-test", "difficulty": "D2", "status": "human_confirmed",
        "required_operations": [{"operation_id": "get_related_deliveries", "expected_parameters": {"sales_order_id": "24"}}],
        "task_relevant_parameters": ["sales_order_id"],
        "expected_outcome": {"deliveries": [{"delivery_id": "80000002", "delivery_status": "completed", "sales_order_id": "24"}]},
    }
    sealed_case = {
        **raw_case, "status": "approved",
        "required_operations": [{"operation_id": "get_related_deliveries", "expected_parameters": pseudonymize({"sales_order_id": "24"}, key.encode())}],
        "expected_outcome": {"deliveries": [coded_value(raw_case["expected_outcome"]["deliveries"][0], key.encode())]},
        "review": {"human_confirmation": {"confirmed_at": "2026-09-15T00:00:00Z"}, "human_approval": {"approved_at": "2026-09-15T00:01:00Z", "researcher": "test"}},
    }
    raw_path = tmp_path / "raw.json"
    sealed_path = tmp_path / "sealed.json"
    policy_path = tmp_path / "policy.json"
    raw_path.write_text(json.dumps({"cases": [raw_case]}), encoding="utf-8")
    sealed_path.write_text(json.dumps({"schema_version": "1.0", "corpus_id": "test", "review_protocol": "human_only", "cases": [sealed_case]}), encoding="utf-8")
    policy_path.write_text(json.dumps({"schema_version": "1.0", "duplicate_call_policy": "incorrect", "maximum_retries": 1, "allowed_optional_operations": {"D2": []}}), encoding="utf-8")
    log = tmp_path / "P02-A-R1.jsonl"
    manifest = {"run_id": "P02-A-R1", "task_id": "P02", "condition": "A", "repetition": 1, "agent": {"tool_call_limit": 8}}
    writer = ExperimentLogWriter(log, manifest, key)
    writer.append({"sequence": 1, **{field: manifest[field] for field in ("run_id", "task_id", "condition", "repetition")}, "event_type": "run_started"})
    writer.append({"sequence": 2, **{field: manifest[field] for field in ("run_id", "task_id", "condition", "repetition")}, "event_type": "tool_call", "actor": "agent", "canonical_operation": "get_related_deliveries", "parameters": {"sales_order_id": "24"}, "success": True})
    answer = tmp_path / "answer.txt"
    answer.write_text('{"sales_orders":[],"deliveries":["80000002"],"billings":[]}', encoding="utf-8")
    assert experiment_cli(["close-run", "--log", str(log), "--answer-file", str(answer)]) == 0
    score_path = tmp_path / "score.json"
    assert experiment_cli(["score-run", "--log", str(log), "--ground-truth", str(sealed_path), "--raw-ground-truth", str(raw_path), "--policy", str(policy_path), "--task-id", "P02", "--output", str(score_path)]) == 0
    assert json.loads(score_path.read_text(encoding="utf-8"))["task_success"] == 1
    log.with_name("P02-A-R1.answer.raw").write_text("modified", encoding="utf-8")
    with pytest.raises(SystemExit, match="archived raw final answer"):
        experiment_cli(["verify-log", "--log", str(log)])
