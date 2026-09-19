import json

from scripts.build_public_research_release import event_projection, project_manifest, write_attempt_lineage


def test_event_projection_omits_identifiers_answers_and_free_text(tmp_path):
    source = tmp_path / "RUN-1.jsonl"
    events = [
        {
            "schema_version": "1.0",
            "run_id": "RUN-1",
            "task_id": "TASK-1",
            "condition": "A",
            "repetition": 1,
            "sequence": 1,
            "event_type": "run_started",
            "timestamp": "private-time",
            "received_at": "private-time",
            "run_context": {"agent": {"model": "model-x", "reasoning": "medium", "tool_call_limit": 8}, "transport": "local-gateway"},
        },
        {
            "schema_version": "1.0",
            "run_id": "RUN-1",
            "task_id": "TASK-1",
            "condition": "A",
            "repetition": 1,
            "sequence": 2,
            "event_type": "tool_call",
            "timestamp": "private-time",
            "call_order": 1,
            "canonical_operation": "get_sales_order",
            "tool_name": "technical_get_order",
            "parameters": {"sales_order_id": "PRIVATE-SAP-ID"},
            "result_summary": {"sales_order_id": "PRIVATE-SAP-ID", "customer_name": "PRIVATE-NAME"},
            "error": "PRIVATE-FREE-TEXT",
            "error_category": "sap_query_error",
            "duration_ms": 120,
            "success": False,
        },
        {
            "schema_version": "1.0",
            "run_id": "RUN-1",
            "task_id": "TASK-1",
            "condition": "A",
            "repetition": 1,
            "sequence": 3,
            "event_type": "run_completed",
            "raw_answer_file": "private-answer.txt",
            "answer_sha256": "private-answer-hash",
            "reported_outcome": {"sales_orders": ["PRIVATE-SAP-ID"]},
            "answer_parse_error": None,
            "termination_reason": "agent_final_answer",
        },
    ]
    source.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    projected, metadata = event_projection(source)
    serialized = json.dumps(projected)

    assert len(projected) == 3
    assert metadata["run_id"] == "RUN-1"
    assert "PRIVATE-SAP-ID" not in serialized
    assert "PRIVATE-NAME" not in serialized
    assert "PRIVATE-FREE-TEXT" not in serialized
    assert "private-answer.txt" not in serialized
    assert "private-answer-hash" not in serialized
    assert "private-time" not in serialized
    assert projected[1]["error_category"] == "sap_query_error"
    assert projected[2]["answer_parse_status"] == "parsed"


def test_manifest_projection_drops_prompt_and_prompt_hash():
    manifest = {
        "run_id": "RUN-1",
        "task_id": "TASK-1",
        "condition": "C",
        "repetition": 1,
        "schedule_index": 3,
        "task_prompt": "PRIVATE PROMPT WITH BUSINESS ID",
        "task_prompt_sha256": "PRIVATE PROMPT HASH",
        "system_prompt_sha256": "PUBLIC SYSTEM PROMPT HASH",
        "agent": {"model": "model-x", "reasoning": "medium", "timeout_seconds": 120, "tool_call_limit": 8},
    }

    projected = project_manifest(manifest, "manifest-hash", "D2", None, "scored")
    serialized = json.dumps(projected)

    assert "PRIVATE PROMPT" not in serialized
    assert "task_prompt_sha256" not in projected
    assert projected["task_id"] == "TASK-1"
    assert projected["difficulty"] == "D2"


def test_attempt_lineage_reports_invalid_and_replacement_counts(tmp_path):
    rows = [
        {"task_id": "TASK-1", "condition": "A", "repetition": 1, "run_id": "RUN-1", "attempt_status": "invalid_attempt"},
        {"task_id": "TASK-1", "condition": "A", "repetition": 1, "run_id": "RUN-1-X1", "attempt_status": "invalid_attempt"},
        {"task_id": "TASK-1", "condition": "A", "repetition": 1, "run_id": "RUN-1-X2", "attempt_status": "scored_replacement"},
    ]
    output = tmp_path / "attempt-lineage.json"

    write_attempt_lineage(output, rows, planned_slots=1, expected_scored=1)
    result = json.loads(output.read_text(encoding="utf-8"))

    assert result["recorded_attempts"] == 3
    assert result["invalid_attempts"] == 2
    assert result["replacement_slots"] == 1
    assert result["slots"][0]["analyzed_run_id"] == "RUN-1-X2"
