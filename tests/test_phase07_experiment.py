from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from experiment.phase07 import ExperimentLogWriter, load_jsonl, score_run, validate_ground_truth
from experiment.cli import main as experiment_cli
from scripts.serve_phase07 import build_phase07_state
from semantic_model.conditions import artifact_bytes, compile_condition_suite
from semantic_model.loader import load_model
from semantic_model.runtime import compile_runtime_bindings


KEY = "phase07-test-key-with-at-least-thirty-two-bytes"


def approved_case() -> dict:
    return {
        "schema_version": "1.0",
        "corpus_id": "pilot",
        "cases": [
            {
                "task_id": "P02",
                "difficulty": "D2",
                "status": "approved",
                "required_operations": [
                    {
                        "operation_id": "get_related_deliveries",
                        "expected_parameters": {"sales_order_id": "hmac-sha256:order"},
                    }
                ],
                "task_relevant_parameters": ["sales_order_id"],
                "expected_outcome": {"deliveries": ["hmac-sha256:delivery"]},
                "review": {
                    "human_confirmation": {"confirmed_at": "2026-09-15T00:00:00Z"},
                    "llm_review": {"verdict": "agree", "model": "review-model-v1", "packet_sha256": "a" * 64},
                },
            }
        ],
    }


def policy() -> dict:
    return {
        "schema_version": "1.0",
        "duplicate_call_policy": "incorrect",
        "maximum_retries": 1,
        "allowed_optional_operations": {"D1": [], "D2": ["get_sales_order"], "D3": ["get_sales_order"]},
    }


def tool_call(operation: str = "get_related_deliveries", *, success: bool = True) -> dict:
    return {
        "event_type": "tool_call",
        "actor": "agent",
        "canonical_operation": operation,
        "parameters": {"sales_order_id": "hmac-sha256:order"},
        "success": success,
        "error": None,
        "error_category": None,
    }


def test_writer_appends_jsonl_and_codes_business_identifiers(tmp_path: Path):
    manifest = {"run_id": "P02-A-R1", "task_id": "P02", "condition": "A"}
    path = tmp_path / "run.jsonl"
    writer = ExperimentLogWriter(path, manifest, KEY)
    writer.append({"sequence": 1, **manifest, "event_type": "run_started", "actor": "system"})
    writer.append({
        "sequence": 2,
        **manifest,
        "event_type": "tool_call",
        "actor": "agent",
        "parameters": {"sales_order_id": "0000001234"},
        "page_state_before": {"selected_order_id": "0000001234"},
    })
    text = path.read_text(encoding="utf-8")
    assert "0000001234" not in text
    assert "hmac-sha256:" in text
    assert len(load_jsonl(path)) == 2


def test_writer_rejects_sequence_gaps_and_existing_log(tmp_path: Path):
    manifest = {"run_id": "P01-A-R1", "task_id": "P01", "condition": "A"}
    path = tmp_path / "run.jsonl"
    writer = ExperimentLogWriter(path, manifest, KEY)
    with pytest.raises(ValueError, match="sequence"):
        writer.append({"sequence": 2, **manifest, "event_type": "run_started"})
    writer.append({"sequence": 1, **manifest, "event_type": "run_started"})
    with pytest.raises(ValueError, match="already exists"):
        ExperimentLogWriter(path, manifest, KEY)


def test_ground_truth_requires_human_and_llm_review():
    document = approved_case()
    validate_ground_truth(document)
    document["cases"][0]["review"]["llm_review"]["verdict"] = "disagree"
    with pytest.raises(ValueError, match="unresolved"):
        validate_ground_truth(document)
    document["cases"][0]["review"]["researcher_resolution"] = {"resolved_at": "2026-09-15T01:00:00Z"}
    validate_ground_truth(document)


def test_human_only_ground_truth_requires_explicit_human_approval():
    document = approved_case()
    document["review_protocol"] = "human_only"
    document["cases"][0]["review"].pop("llm_review")
    with pytest.raises(ValueError, match="human approval"):
        validate_ground_truth(document)
    document["cases"][0]["review"]["human_approval"] = {
        "researcher": "researcher-01",
        "approved_at": "2026-09-15T01:00:00Z",
        "protocol": "human_only",
    }
    validate_ground_truth(document)


def test_human_only_cli_approval_preserves_protocol(tmp_path: Path):
    document = approved_case()
    document["review_protocol"] = "human_only"
    case = document["cases"][0]
    case["status"] = "human_confirmed"
    case["review"].pop("llm_review")
    case["review"]["human_confirmation"]["researcher"] = "researcher-01"
    path = tmp_path / "ground-truth.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    assert experiment_cli(["approve-ground-truth", "--ground-truth", str(path), "--task-id", "P02", "--output", str(path)]) == 0
    approved = json.loads(path.read_text(encoding="utf-8"))
    assert approved["cases"][0]["status"] == "approved"
    assert approved["cases"][0]["review"]["human_approval"]["protocol"] == "human_only"
    validate_ground_truth(approved)


def test_score_separates_decision_completeness_and_answer_quality():
    case = approved_case()["cases"][0]
    perfect = score_run([tool_call()], case, policy(), {"deliveries": ["hmac-sha256:delivery"]})
    assert perfect["tool_selection_accuracy"] == 1
    assert perfect["parameter_accuracy"] == 1
    assert perfect["task_success"] == 1

    incomplete = score_run([], case, policy(), {"deliveries": []})
    assert incomplete["tool_selection_accuracy"] == 0
    assert incomplete["task_success"] == 0

    synthesis = score_run([tool_call()], case, policy(), {"deliveries": []})
    assert synthesis["tool_selection_accuracy"] == 1
    assert synthesis["task_success"] == 0
    assert "answer_synthesis_error" in synthesis["error_categories"]


def test_score_flags_wrong_and_duplicate_tools():
    case = approved_case()["cases"][0]
    result = score_run(
        [tool_call("get_related_billing_documents"), tool_call(), tool_call()],
        case,
        policy(),
        {"deliveries": ["hmac-sha256:delivery"]},
    )
    assert result["tool_selection_accuracy"] == pytest.approx(1 / 3)
    assert "tool_selection_error" in result["error_categories"]


def test_score_allows_only_policy_bounded_retry_after_retryable_failure():
    case = approved_case()["cases"][0]
    failed = tool_call(success=False)
    failed["error"] = {"retryable": True}
    failed["error_category"] = "sap_query_error"
    result = score_run(
        [failed, tool_call(), tool_call()],
        case,
        policy(),
        {"deliveries": ["hmac-sha256:delivery"]},
    )
    assert result["tool_selection_accuracy"] == pytest.approx(2 / 3)
    assert result["task_success"] == 1
    assert set(result["error_categories"]) == {"sap_query_error", "tool_selection_error"}


def test_phase07_state_reuses_selected_catalog_and_exposes_no_ground_truth(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    model = load_model(root / "semantic_models/sap_sd/model.yaml")
    bindings = compile_runtime_bindings(model)
    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(json.dumps(bindings), encoding="utf-8")
    catalog_dir = tmp_path / "catalogs"
    catalog_dir.mkdir()
    catalogs, _ = compile_condition_suite(model)
    names = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}
    for condition, catalog in catalogs.items():
        (catalog_dir / names[condition]).write_bytes(artifact_bytes(catalog))
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("ok", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "SAP_USER=test\nSAP_PASSWORD=test\n"
        "SAP_ODATA_BASE_URL=https://sap.example/sales/\n"
        "SAP_DELIVERY_ODATA_BASE_URL=https://sap.example/delivery/\n"
        "SAP_BILLING_ODATA_BASE_URL=https://sap.example/billing/\n"
        f"PHASE07_HMAC_KEY={KEY}\n",
        encoding="utf-8",
    )
    manifest = tmp_path / "run.json"
    manifest.write_text(json.dumps({
        "schema_version": "1.0", "run_id": "P01-B-R1", "task_id": "P01", "condition": "B",
        "repetition": 1, "transport": "direct-browser", "agent": {"model": "test-model"},
        "ground_truth_sha256": "a" * 64, "scoring_policy_sha256": "b" * 64,
    }), encoding="utf-8")
    state = build_phase07_state(Namespace(
        run_manifest=manifest, frontend_root=frontend, catalog_dir=catalog_dir, bindings=bindings_path,
        env=env, log_dir=tmp_path / "logs",
    ))
    assert state["catalog"]["condition"] == "B"
    assert state["config"]["experiment"]["task_id"] == "P01"
    assert "ground_truth" not in json.dumps(state["config"])
