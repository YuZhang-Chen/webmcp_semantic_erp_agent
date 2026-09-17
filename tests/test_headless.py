from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from experiment.headless import GatewayRuntimeExecutor, OpenAIResponsesAdapter, ReplayExecutor, ToolCallLimitExceeded, catalog_to_openai_tools
from experiment.phase07 import ExperimentLogWriter, file_sha256, load_jsonl
from experiment.phase08 import build_manifest, build_plan
from experiment.phase08_cli import archive_headless_answer, ordered_batch_manifests


ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / "build" / "phase-05"


def test_catalogs_convert_to_four_function_tools():
    for name in ("a-technical-tools.json", "b-typed-tools.json", "c-semantic-tools.json"):
        catalog = json.loads((CATALOG_DIR / name).read_text(encoding="utf-8"))
        tools = catalog_to_openai_tools(catalog)
        assert len(tools) == 4
        assert all(tool["type"] == "function" and "parameters" in tool for tool in tools)


def test_replay_executor_requires_exact_canonical_request():
    key = json.dumps({"operation_id": "get_sales_order", "arguments": {"sales_order_id": "10569"}}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    executor = ReplayExecutor({key: {"sales_order": "10569"}})
    assert executor("get_sales_order", {"sales_order_id": "10569"}) == {"sales_order": "10569"}


def test_gateway_executor_sends_configured_sap_client_and_language(monkeypatch):
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        return _Response({"d": {"results": []}})

    monkeypatch.setattr("experiment.headless.urllib.request.urlopen", opener)
    executor = GatewayRuntimeExecutor(
        {},
        {
            "services": {"sales_order_service": "/api/odata/sales_order_service"},
            "client": "600",
            "language": "ZF",
        },
    )
    assert executor._get("sales_order_service", "A_SalesOrder", {"$top": "1"}) == []
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(captured["url"]).query)
    assert query["sap-client"] == ["600"]
    assert query["sap-language"] == ["ZF"]


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode()


def test_openai_adapter_runs_multiple_tool_turns_without_previous_response_id():
    responses = iter([
        {"output": [{"type": "function_call", "name": "read_A_SalesOrder", "call_id": "call-1", "arguments": '{"SalesOrder":"10569"}'}]},
        {"output": [], "output_text": '{"sales_orders":["10569"],"deliveries":[],"billings":[]}'},
    ])
    requests = []

    def opener(request, timeout):
        requests.append(json.loads(request.data.decode()))
        return _Response(next(responses))

    adapter = OpenAIResponsesAdapter(api_key="x", model="gpt-test", opener=opener)
    result = adapter.run(
        "system", "task", [{"type": "function", "name": "read_A_SalesOrder", "_operation_id": "get_sales_order", "parameters": {"type": "object"}}],
        lambda operation, arguments: {"sales_order": arguments["sales_order_id"]}, condition="A", timeout_seconds=5, tool_call_limit=8,
    )
    assert result.tool_calls == 1
    assert json.loads(result.answer)["sales_orders"] == ["10569"]
    assert all("previous_response_id" not in request for request in requests)


def test_openai_adapter_reports_rejected_over_budget_attempt_without_execution():
    responses = iter([
        {"output": [{"type": "function_call", "name": "read_A_SalesOrder", "call_id": "call-1", "arguments": '{"SalesOrder":"10569"}'}, {"type": "function_call", "name": "read_A_SalesOrder", "call_id": "call-2", "arguments": '{"SalesOrder":"10569"}'}]},
    ])
    observed = []

    def opener(request, timeout):
        return _Response(next(responses))

    adapter = OpenAIResponsesAdapter(api_key="x", model="gpt-test", opener=opener)
    with pytest.raises(ToolCallLimitExceeded):
        adapter.run("system", "task", [{"type": "function", "name": "read_A_SalesOrder", "_operation_id": "get_sales_order", "parameters": {"type": "object"}}], lambda *_: {"sales_order": {}}, condition="A", timeout_seconds=5, tool_call_limit=1, observer=lambda *args: observed.append(args))
    assert len(observed) == 2
    assert observed[-1][3] is False
    assert isinstance(observed[-1][-1], ToolCallLimitExceeded)


def test_azure_openai_adapter_uses_v1_endpoint_and_api_key_header(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "azure_openai")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.6-sol")
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["api_key"] = request.get_header("Api-key")
        return _Response({"output": [], "output_text": '{"sales_orders":[],"deliveries":[],"billings":[]}'})

    adapter = OpenAIResponsesAdapter(opener=opener)
    adapter.run("system", "task", [], lambda *_: {}, condition="A", timeout_seconds=5, tool_call_limit=8)
    assert adapter.provider == "azure-openai-responses"
    assert captured == {"url": "https://example.openai.azure.com/openai/v1/responses", "api_key": "azure-key"}


def _pilot_case(task_id: str, difficulty: str, order: str) -> dict:
    return {
        "task_id": task_id,
        "difficulty": difficulty,
        "status": "approved",
        "required_operations": [{"operation_id": "get_sales_order", "expected_parameters": {"sales_order_id": order}}],
        "task_relevant_parameters": ["sales_order_id"],
        "expected_outcome": {"sales_orders": [order], "deliveries": [], "billings": []},
        "review": {
            "human_confirmation": {"researcher": "test", "confirmed_at": "2026-09-15T00:00:00Z"},
            "human_approval": {"researcher": "test", "approved_at": "2026-09-15T00:01:00Z", "protocol": "human_only"},
        },
    }


def _pilot_plan() -> dict:
    cases = [
        _pilot_case("P01", "D1", "1001"),
        _pilot_case("P02", "D2", "1002"),
        _pilot_case("P03", "D2", "1003"),
        _pilot_case("P04", "D3", "1004"),
        _pilot_case("P05", "D3", "1005"),
    ]
    corpus = {"schema_version": "1.0", "corpus_id": "headless-test", "review_protocol": "human_only", "cases": cases}
    policy = {
        "schema_version": "1.0",
        "duplicate_call_policy": "incorrect",
        "maximum_retries": 1,
        "allowed_optional_operations": {"D1": [], "D2": [], "D3": []},
    }
    return build_plan(corpus, policy, mode="pilot", raw_corpus=corpus)


def test_headless_batch_uses_frozen_plan_order(tmp_path: Path):
    plan = _pilot_plan()
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    for entry in reversed(plan["schedule"]):
        manifest = build_manifest(plan, entry)
        (manifest_dir / f"{entry['run_id']}.json").write_text(json.dumps(manifest), encoding="utf-8")
    paths = ordered_batch_manifests(manifest_dir, plan)
    assert [path.stem for path in paths] == [entry["run_id"] for entry in plan["schedule"]]


def test_headless_answer_archive_produces_scoreable_completion_contract(tmp_path: Path):
    plan = _pilot_plan()
    manifest = build_manifest(plan, plan["schedule"][0])
    log_path = tmp_path / "run.jsonl"
    output_path = tmp_path / "answers" / "run.txt"
    writer = ExperimentLogWriter(log_path, manifest, "x" * 32)
    writer.append({
        "schema_version": "1.0",
        "run_id": manifest["run_id"],
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "repetition": manifest["repetition"],
        "sequence": 1,
        "timestamp": "2026-09-16T00:00:00Z",
        "event_type": "run_started",
        "actor": "system",
    })
    answer = '{"sales_orders":["1001"],"deliveries":[],"billings":[]}'
    completion = archive_headless_answer(answer, output_path, log_path)
    writer.append({
        "schema_version": "1.0",
        "run_id": manifest["run_id"],
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "repetition": manifest["repetition"],
        "sequence": 2,
        "timestamp": "2026-09-16T00:00:01Z",
        "event_type": "run_completed",
        "actor": "system",
        **completion,
    })
    events = load_jsonl(log_path)
    completed = events[-1]
    raw_path = log_path.with_name(completed["raw_answer_file"])
    assert raw_path.read_text(encoding="utf-8") == answer
    assert file_sha256(raw_path) == completed["answer_sha256"]
    assert completed["reported_outcome"]["sales_orders"][0].startswith("hmac-sha256:")
