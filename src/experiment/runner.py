"""Phase 07 pilot runner planning and answer-boundary helpers.

The runner deliberately stops at the browser boundary: it creates immutable
run manifests and validates the artifacts that a fresh Codex task must use.
The Desktop built-in browser remains a human-started surface when the local
Codex integration cannot attach a task to a specific tab.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .phase07 import canonical_bytes, coded_value, file_sha256, pseudonymize

CONDITIONS = ("A", "B", "C")
TASKS = ("P01", "P02", "P03", "P04", "P05")
ANSWER_KEYS = ("sales_orders", "deliveries", "billings")
MAX_REPLACEMENTS = 2
SYSTEM_PROMPT = (
    "你是 SAP SD 文件查詢 Agent。請僅使用目前瀏覽器頁面提供的 Site Tools 查詢。"
    "根據使用者任務自行選擇工具與參數。最終回答必須是單一 JSON 物件，"
    "恰好包含 sales_orders、deliveries、billings 三個欄位，值皆為文件 ID 字串陣列；"
    "沒有文件時使用空陣列。不要附加說明、工具流程或推理。"
)


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def validate_reported_outcome(value: Any) -> dict[str, list[str]]:
    """Validate the fixed ID-only answer contract used by the pilot."""
    if not isinstance(value, Mapping) or set(value) != set(ANSWER_KEYS):
        raise ValueError("reported outcome must contain exactly sales_orders, deliveries and billings")
    result: dict[str, list[str]] = {}
    for key in ANSWER_KEYS:
        items = value[key]
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise ValueError(f"reported outcome field {key} must be an array of non-empty strings")
        result[key] = list(items)
    return result


def parse_reported_outcome(answer_file: Path) -> dict[str, list[str]]:
    """Parse raw final output as strict JSON; never repair or rewrite it."""
    raw = answer_file.read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"final answer is not valid JSON: {exc.msg}") from exc
    return validate_reported_outcome(value)


def project_id_only_case(raw_case: Mapping[str, Any], sealed_case: Mapping[str, Any], hmac_key: str) -> dict[str, Any]:
    """Verify an approved sealed case, then derive its ID-only score target.

    The approved corpus is left intact. Each raw document must reproduce the
    sealed HMAC before its identifier may be used by the offline scorer.
    """
    if raw_case.get("task_id") != sealed_case.get("task_id") or raw_case.get("candidate_id") != sealed_case.get("candidate_id"):
        raise ValueError("raw and sealed case identities do not match")
    if sealed_case.get("status") != "approved":
        raise ValueError("ID-only score projection requires an approved case")
    if not isinstance(hmac_key, str) or len(hmac_key.encode("utf-8")) < 32:
        raise ValueError("HMAC_KEY must contain at least 32 bytes")
    key = hmac_key.encode("utf-8")
    raw_operations = raw_case.get("required_operations", [])
    sealed_operations = sealed_case.get("required_operations", [])
    if len(raw_operations) != len(sealed_operations):
        raise ValueError("raw and sealed required operations differ")
    for raw_operation, sealed_operation in zip(raw_operations, sealed_operations):
        if raw_operation.get("operation_id") != sealed_operation.get("operation_id") or pseudonymize(raw_operation.get("expected_parameters", {}), key) != sealed_operation.get("expected_parameters"):
            raise ValueError("raw and sealed canonical parameters differ")
    id_fields = {"sales_orders": "sales_order_id", "deliveries": "delivery_id", "billings": "billing_document_id"}
    raw_outcome = raw_case.get("expected_outcome", {})
    sealed_outcome = sealed_case.get("expected_outcome", {})
    if set(raw_outcome) != set(sealed_outcome):
        raise ValueError("raw and sealed expected outcome fields differ")
    projected: dict[str, list[str]] = {}
    for field, items in raw_outcome.items():
        if field not in id_fields or not isinstance(items, list) or not isinstance(sealed_outcome[field], list) or len(items) != len(sealed_outcome[field]):
            raise ValueError("expected outcome shape does not support ID-only projection")
        projected[field] = []
        for raw_item, sealed_item in zip(items, sealed_outcome[field]):
            if not isinstance(raw_item, Mapping) or coded_value(raw_item, key) != sealed_item:
                raise ValueError("raw SAP document does not reproduce the approved sealed HMAC")
            document_id = raw_item.get(id_fields[field])
            if not isinstance(document_id, str) or not document_id:
                raise ValueError("approved SAP document lacks the expected ID")
            projected[field].append(coded_value(document_id, key))
    return {**sealed_case, "expected_outcome": projected}


def build_task_prompts(ground_truth: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """Create fixed Traditional-Chinese prompts without downstream answers."""
    prompts: dict[str, str] = {}
    for case in ground_truth.get("cases", []):
        task_id = case.get("task_id")
        if task_id not in TASKS:
            continue
        operations = case.get("required_operations", [])
        if task_id == "P01":
            order_id = operations[0].get("expected_parameters", {}).get("sales_order_id", "")
            prompts[task_id] = f"請查詢 Sales Order {order_id} 的單一文件資訊，並以固定 JSON 格式回答。"
        elif task_id == "P02":
            order_id = operations[0].get("expected_parameters", {}).get("sales_order_id", "")
            prompts[task_id] = f"請查詢 Sales Order {order_id} 對應的交貨文件，並以固定 JSON 格式回答。"
        elif task_id == "P03":
            order_id = operations[0].get("expected_parameters", {}).get("sales_order_id", "")
            prompts[task_id] = f"請查詢 Sales Order {order_id} 對應的交貨與請款文件，並以固定 JSON 格式回答。"
        else:
            criteria = next((item.get("expected_parameters", {}).get("criteria") for item in operations if item.get("operation_id") == "search_sales_orders"), None)
            if not isinstance(criteria, Mapping):
                raise ValueError(f"{task_id} lacks governed search criteria")
            labels = {
                "customer_id": "客戶",
                "order_date_from": "訂單日期起",
                "order_date_to": "訂單日期迄",
                "order_status": "訂單狀態",
            }
            criteria_text = "、".join(f"{labels[key]}={criteria[key]}" for key in labels if key in criteria)
            purpose = "交貨文件" if task_id == "P04" else "交貨與請款文件"
            prompts[task_id] = f"請依條件 {criteria_text} 找到唯一 Sales Order，再查詢其對應的{purpose}，並以固定 JSON 格式回答。"
    missing = set(TASKS) - set(prompts)
    if missing:
        raise ValueError("missing pilot tasks: " + ", ".join(sorted(missing)))
    if any("hmac-sha256:" in text for text in prompts.values()):
        raise ValueError("prompt source contains sealed HMAC identifiers; provide the researcher-private raw corpus")
    return {task: {"task_id": task, "language": "zh-Hant", "text": prompts[task], "sha256": _hash(prompts[task])} for task in TASKS}


def interleaved_schedule() -> list[dict[str, Any]]:
    """Return a deterministic schedule with condition order rotated per task."""
    schedule: list[dict[str, Any]] = []
    for task_index, task_id in enumerate(TASKS):
        for offset in range(3):
            condition = CONDITIONS[(task_index + offset) % len(CONDITIONS)]
            schedule.append({"index": len(schedule) + 1, "task_id": task_id, "condition": condition, "repetition": 1, "run_id": f"{task_id}-{condition}-R1"})
    return schedule


def build_pilot_plan(ground_truth: Mapping[str, Any], policy: Mapping[str, Any], *, prompt_source: Mapping[str, Any] | None = None, ground_truth_sha256: str | None = None, scoring_policy_sha256: str | None = None, model: str = "gpt-5.6-sol", reasoning: str = "medium", timeout_seconds: int = 120, tool_call_limit: int = 8) -> dict[str, Any]:
    prompts = build_task_prompts(prompt_source or ground_truth)
    gt_hash = ground_truth_sha256 or _hash(ground_truth)
    policy_hash = scoring_policy_sha256 or _hash(policy)
    return {
        "schema_version": "1.0",
        "protocol": "phase07-pilot-calibration",
        "ground_truth_sha256": gt_hash,
        "scoring_policy_sha256": policy_hash,
        "task_prompt_sha256": {task: item["sha256"] for task, item in prompts.items()},
        "system_prompt": SYSTEM_PROMPT,
        "system_prompt_sha256": _hash(SYSTEM_PROMPT),
        "tasks": prompts,
        "agent": {"provider": "codex", "model": model, "reasoning": reasoning, "temperature": None, "timeout_seconds": timeout_seconds, "tool_call_limit": tool_call_limit},
        "isolation": {"fresh_session_per_run": True, "allow_repository_access": False, "allow_ground_truth_access": False, "allow_scorer_access": False},
        "replacement_policy": {"max_replacements": MAX_REPLACEMENTS, "invalid_runs_are_not_scored": True, "preserve_original": True},
        "answer_schema": {"type": "object", "additionalProperties": False, "required": list(ANSWER_KEYS), "properties": {key: {"type": "array", "items": {"type": "string", "minLength": 1}} for key in ANSWER_KEYS}},
        "schedule": interleaved_schedule(),
    }


def build_run_manifest(plan: Mapping[str, Any], entry: Mapping[str, Any], *, transport: str = "local-gateway", catalog_sha256: str = "", runtime_sha256: str = "") -> dict[str, Any]:
    task_id, condition = str(entry["task_id"]), str(entry["condition"])
    return {
        "schema_version": "1.0", "run_id": entry["run_id"], "task_id": task_id, "condition": condition, "repetition": 1,
        "transport": transport, "ground_truth_sha256": plan["ground_truth_sha256"], "scoring_policy_sha256": plan["scoring_policy_sha256"],
        "task_prompt": plan["tasks"][task_id]["text"], "task_prompt_sha256": plan["task_prompt_sha256"][task_id],
        "system_prompt_sha256": plan.get("system_prompt_sha256"),
        "schedule_index": entry["index"], "catalog_sha256": catalog_sha256, "runtime_sha256": runtime_sha256,
        "agent": dict(plan["agent"]), "isolation": dict(plan["isolation"]), "replacement_policy": dict(plan["replacement_policy"]),
    }


def integration_check(plan: Mapping[str, Any], *, frontend_root: Path, catalog_dir: Path, bindings: Path) -> dict[str, Any]:
    """Validate the non-UI half of the integration gate."""
    missing = [str(path) for path in (frontend_root / "index.html", bindings) if not path.is_file()]
    catalogs = {condition: catalog_dir / {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}[condition] for condition in CONDITIONS}
    missing.extend(str(path) for path in catalogs.values() if not path.is_file())
    catalog_tool_counts: dict[str, int | None] = {}
    for condition, path in catalogs.items():
        if not path.is_file():
            catalog_tool_counts[condition] = None
            continue
        try:
            catalog_tool_counts[condition] = len(json.loads(path.read_text(encoding="utf-8")).get("tools", []))
        except (OSError, json.JSONDecodeError, AttributeError):
            catalog_tool_counts[condition] = 0
    if any(count != 4 for count in catalog_tool_counts.values()):
        missing.append("each condition catalog must expose exactly four Site Tools")
    schedule = plan.get("schedule", [])
    if len(schedule) != 15 or len({item.get("run_id") for item in schedule if isinstance(item, Mapping)}) != 15:
        missing.append("pilot schedule must contain 15 unique runs")
    agent = plan.get("agent", {})
    if agent.get("model") != "gpt-5.6-sol" or agent.get("reasoning") != "medium" or agent.get("timeout_seconds") != 120 or agent.get("tool_call_limit") != 8:
        missing.append("agent settings must be gpt-5.6-sol / medium / 120 seconds / 8 calls")
    return {"schema_version": "1.0", "valid": not missing, "browser_attachment": "manual-start-allowed", "required_site_tools": 4, "missing": missing, "frontend_sha256": file_sha256(frontend_root / "index.html") if (frontend_root / "index.html").is_file() else None, "catalogs": {condition: file_sha256(path) if path.is_file() else None for condition, path in catalogs.items()}, "catalog_tool_counts": catalog_tool_counts, "next_step": "Open the workbench in ChatGPT Desktop built-in browser, verify four Site Tools, then press Start once."}
