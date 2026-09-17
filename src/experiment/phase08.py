"""Phase 08 pilot and formal A/B/C experiment planning and analysis.

This module deliberately keeps the Phase 07 artifacts immutable.  It owns the
larger schedules, their manifests, pre-flight gates, replacement lineage and
offline aggregation only; live SAP evidence remains researcher-private.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase07 import (
    canonical_bytes,
    file_sha256,
    load_jsonl,
    validate_ground_truth,
    validate_scoring_policy,
)
from .runner import ANSWER_KEYS, CONDITIONS, SYSTEM_PROMPT

PHASE08_SEED = 20260915
PHASE08_SCHEMA = "phase08-1.0"
FORMAL_QUOTA = {"D1": 4, "D2": 8, "D3": 8}
PILOT_QUOTA = {"D1": 1, "D2": 2, "D3": 2}
MODEL_DEFAULT = "gpt-5.6-sol"
REASONING_DEFAULT = "medium"
TIMEOUT_DEFAULT = 120
TOOL_CALL_LIMIT_DEFAULT = 8
MAX_REPLACEMENTS = 2


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _task_prompt(case: Mapping[str, Any]) -> str:
    """Build a fixed prompt from researcher-private raw case data."""
    task_id = str(case.get("task_id", ""))
    operations = case.get("required_operations", [])
    if not isinstance(operations, list) or not operations:
        raise ValueError(f"{task_id} has no required operations")
    params = [item.get("expected_parameters", {}) for item in operations if isinstance(item, Mapping)]
    order_id = next((item.get("sales_order_id") for item in params if item.get("sales_order_id")), None)
    criteria = next((item.get("criteria") for item in params if isinstance(item.get("criteria"), Mapping)), None)
    operation_ids = {str(item.get("operation_id")) for item in operations}

    if {"get_related_deliveries", "get_related_billing_documents"} <= operation_ids:
        purpose = "出貨與請款資料"
    elif "get_related_deliveries" in operation_ids:
        purpose = "出貨資料"
    elif "get_related_billing_documents" in operation_ids:
        purpose = "請款資料"
    else:
        purpose = "訂單資料"

    def natural_date(value: Any) -> str:
        parts = str(value).split("-")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            return f"{int(parts[0])} 年 {int(parts[1])} 月 {int(parts[2])} 日"
        return str(value)

    if criteria:
        customer = str(criteria.get("customer_id", "指定客戶"))
        date_from = criteria.get("order_date_from")
        date_to = criteria.get("order_date_to")
        if date_from and date_to and date_from == date_to:
            date_text = f"在 {natural_date(date_from)}"
        elif date_from and date_to:
            date_text = f"從 {natural_date(date_from)} 到 {natural_date(date_to)}"
        elif date_from:
            date_text = f"自 {natural_date(date_from)} 起"
        elif date_to:
            date_text = f"截至 {natural_date(date_to)}"
        else:
            date_text = ""
        status = {
            "completed": "已完成",
            "partially_completed": "部分完成",
            "not_started": "尚未開始",
        }.get(str(criteria.get("order_status", "")), "")
        qualifier = "".join(part for part in (date_text, status) if part)
        text = f"請找出客戶 {customer} {qualifier}的訂單，並查詢該筆訂單的{purpose}，最後以固定 JSON 格式回答。"
    elif order_id:
        if purpose == "訂單資料":
            text = f"請幫我查詢編號 {order_id} 的訂單資料，並以固定 JSON 格式回答。"
        else:
            text = f"請幫我查詢訂單 {order_id} 的{purpose}，並以固定 JSON 格式回答。"
    else:
        text = f"請完成 {task_id} 指定的 SAP SD 文件查詢，並以固定 JSON 格式回答。"
    return text


def build_task_prompts(raw_corpus: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    prompts: dict[str, dict[str, str]] = {}
    for case in raw_corpus.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        text = _task_prompt(case)
        if "hmac-sha256:" in text:
            raise ValueError("prompt source contains sealed identifiers; pass researcher-private raw corpus")
        prompts[str(case["task_id"])] = {
            "task_id": str(case["task_id"]),
            "language": "zh-Hant",
            "text": text,
            "sha256": sha256_value(text),
        }
    if not prompts:
        raise ValueError("corpus contains no tasks")
    return prompts


def _task_ids(mode: str, count: int) -> list[str]:
    if mode == "pilot":
        if count != 5:
            raise ValueError("pilot requires exactly five tasks")
        return [f"P08-P{i:02d}" for i in range(1, 6)]
    if mode == "formal":
        if count != 20:
            raise ValueError("formal experiment requires exactly twenty tasks")
        return [f"F08-T{i:02d}" for i in range(1, 21)]
    raise ValueError("mode must be pilot or formal")


def _normalise_cases(corpus: Mapping[str, Any], mode: str) -> list[dict[str, Any]]:
    cases = [dict(case) for case in corpus.get("cases", [])]
    ids = _task_ids(mode, len(cases))
    # Existing pilot cases are P01-P05.  Formal corpora must already use the
    # stable F08 IDs; pilot cases are remapped into the Phase 08 namespace.
    if mode == "formal" and {case.get("task_id") for case in cases} != set(ids):
        raise ValueError("formal corpus task IDs must be F08-T01 through F08-T20")
    if mode == "pilot":
        for case, task_id in zip(cases, ids):
            case["task_id"] = task_id
    return cases


def validate_phase08_corpus(
    corpus: Mapping[str, Any],
    mode: str,
    *,
    raw_corpus: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate approved corpus shape and the fixed D1/D2/D3 quotas."""
    validate_ground_truth(corpus)
    if corpus.get("source_id") and corpus.get("source_id") != "webmcp.sap_sd.odata":
        raise ValueError("Phase 08 corpus source_id must be webmcp.sap_sd.odata")
    cases = _normalise_cases(corpus, mode)
    quota = PILOT_QUOTA if mode == "pilot" else FORMAL_QUOTA
    counts = Counter(str(case.get("difficulty")) for case in cases)
    if dict(counts) != quota:
        raise ValueError(f"{mode} difficulty quota must be {quota}, got {dict(counts)}")
    if corpus.get("review_protocol", "human_plus_llm") != "human_only":
        raise ValueError("Phase 08 requires the fixed human_only review protocol")
    for case in cases:
        if case.get("status") != "approved":
            raise ValueError(f"case {case.get('task_id')} is not approved")
    if mode == "formal" and raw_corpus is not None:
        raw_cases = {str(item.get("task_id")): item for item in raw_corpus.get("cases", []) if isinstance(item, Mapping)}
        order_ids: list[str] = []
        for case in cases:
            raw = raw_cases.get(str(case.get("task_id")))
            if not raw:
                raise ValueError(f"raw corpus lacks {case.get('task_id')}")
            case_order_ids: set[str] = set()
            for operation in raw.get("required_operations", []):
                params = operation.get("expected_parameters", {})
                if isinstance(params, Mapping) and isinstance(params.get("sales_order_id"), str):
                    case_order_ids.add(params["sales_order_id"])
            if len(case_order_ids) != 1:
                raise ValueError(f"formal task {case.get('task_id')} must use one Sales Order identifier")
            order_ids.append(next(iter(case_order_ids)))
            if case.get("difficulty") == "D3":
                has_search = any(item.get("operation_id") == "search_sales_orders" for item in raw.get("required_operations", []))
                if not has_search:
                    raise ValueError(f"D3 case {case.get('task_id')} requires search_sales_orders")
        if len(order_ids) != len(set(order_ids)):
            raise ValueError("formal tasks must use distinct Sales Order identifiers")
    return {"valid": True, "mode": mode, "case_count": len(cases), "difficulty_counts": dict(counts), "source_id": "webmcp.sap_sd.odata"}


def build_schedule(mode: str, *, seed: int = PHASE08_SEED) -> list[dict[str, Any]]:
    count = 5 if mode == "pilot" else 20 if mode == "formal" else 0
    task_ids = _task_ids(mode, count)
    rng = random.Random(seed)
    schedule: list[dict[str, Any]] = []
    for repetition in range(1, 4):
        ordered = list(task_ids)
        rng.shuffle(ordered)
        for index, task_id in enumerate(ordered):
            for condition_offset in range(3):
                condition = CONDITIONS[(index + repetition - 1 + condition_offset) % 3]
                schedule.append({
                    "index": len(schedule) + 1,
                    "task_id": task_id,
                    "condition": condition,
                    "repetition": repetition,
                    "run_id": f"{task_id}-{condition}-R{repetition}",
                })
    return schedule


def validate_schedule(schedule: Sequence[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    expected_tasks = set(_task_ids(mode, 5 if mode == "pilot" else 20))
    expected_count = len(expected_tasks) * 3 * 3
    if len(schedule) != expected_count:
        raise ValueError(f"{mode} schedule must contain {expected_count} runs")
    run_ids = [str(item.get("run_id")) for item in schedule]
    if len(set(run_ids)) != expected_count:
        raise ValueError("schedule run IDs must be unique")
    task_condition_reps = Counter((item.get("task_id"), item.get("condition"), item.get("repetition")) for item in schedule)
    if any(count != 1 for count in task_condition_reps.values()) or len(task_condition_reps) != expected_count:
        raise ValueError("every task × condition × repetition slot must occur exactly once")
    task_counts = Counter(item.get("task_id") for item in schedule)
    if set(task_counts) != expected_tasks or any(value != 9 for value in task_counts.values()):
        raise ValueError("each task must occur nine times")
    condition_counts = Counter(item.get("condition") for item in schedule)
    if condition_counts != Counter({"A": expected_count // 3, "B": expected_count // 3, "C": expected_count // 3}):
        raise ValueError("conditions must be balanced")
    return {"valid": True, "run_count": expected_count, "task_count": len(expected_tasks), "condition_counts": dict(condition_counts), "mode": mode}


def build_plan(
    corpus: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    mode: str,
    raw_corpus: Mapping[str, Any] | None = None,
    seed: int = PHASE08_SEED,
    ground_truth_sha256: str | None = None,
    scoring_policy_sha256: str | None = None,
    model: str = MODEL_DEFAULT,
    reasoning: str = REASONING_DEFAULT,
    timeout_seconds: int = TIMEOUT_DEFAULT,
    tool_call_limit: int = TOOL_CALL_LIMIT_DEFAULT,
) -> dict[str, Any]:
    validate_phase08_corpus(corpus, mode, raw_corpus=raw_corpus)
    validate_scoring_policy(policy)
    raw_source = raw_corpus or corpus
    prompts = build_task_prompts(raw_source)
    cases = _normalise_cases(corpus, mode)
    # Map Phase 07 P01-P05 prompt source onto P08-P01-P05.
    if mode == "pilot" and set(prompts) >= {f"P{i:02d}" for i in range(1, 6)}:
        prompts = {f"P08-{key}": {**value, "task_id": f"P08-{key}"} for key, value in prompts.items() if key.startswith("P")}
    expected_tasks = {str(case["task_id"]) for case in cases}
    missing = expected_tasks - set(prompts)
    if missing:
        raise ValueError("raw corpus lacks prompts for: " + ", ".join(sorted(missing)))
    schedule = build_schedule(mode, seed=seed)
    validate_schedule(schedule, mode)
    plan = {
        "schema_version": PHASE08_SCHEMA,
        "protocol": "phase08-ab-c-experiment",
        "mode": mode,
        "seed": seed,
        "source_id": "webmcp.sap_sd.odata",
        "corpus_id": corpus.get("corpus_id"),
        "ground_truth_sha256": ground_truth_sha256 or sha256_value(corpus),
        "scoring_policy_sha256": scoring_policy_sha256 or sha256_value(policy),
        "task_prompt_sha256": {task: prompts[task]["sha256"] for task in sorted(expected_tasks)},
        "tasks": prompts,
        "system_prompt": SYSTEM_PROMPT,
        "system_prompt_sha256": sha256_value(SYSTEM_PROMPT),
        "agent": {"provider": "codex", "model": model, "reasoning": reasoning, "temperature": None, "timeout_seconds": timeout_seconds, "tool_call_limit": tool_call_limit},
        "isolation": {"fresh_session_per_run": True, "allow_repository_access": False, "allow_ground_truth_access": False, "allow_scorer_access": False},
        "replacement_policy": {"max_replacements": MAX_REPLACEMENTS, "invalid_runs_are_not_scored": True, "preserve_original": True},
        "answer_schema": {"type": "object", "additionalProperties": False, "required": list(ANSWER_KEYS)},
        "schedule": schedule,
    }
    plan["schedule_sha256"] = sha256_value(schedule)
    return plan


def build_manifest(plan: Mapping[str, Any], entry: Mapping[str, Any], *, transport: str = "local-gateway", catalog_sha256: str = "", runtime_sha256: str = "", replaces_run_id: str | None = None) -> dict[str, Any]:
    task_id = str(entry["task_id"])
    manifest = {
        "schema_version": PHASE08_SCHEMA,
        "protocol": plan["protocol"],
        "mode": plan["mode"],
        "source_id": plan.get("source_id"),
        "corpus_id": plan.get("corpus_id"),
        "run_id": entry["run_id"],
        "task_id": task_id,
        "condition": entry["condition"],
        "repetition": entry["repetition"],
        "schedule_index": entry["index"],
        "schedule_sha256": plan["schedule_sha256"],
        "ground_truth_sha256": plan["ground_truth_sha256"],
        "scoring_policy_sha256": plan["scoring_policy_sha256"],
        "task_prompt": plan["tasks"][task_id]["text"],
        "task_prompt_sha256": plan["task_prompt_sha256"][task_id],
        "system_prompt_sha256": plan["system_prompt_sha256"],
        "transport": transport,
        "catalog_sha256": catalog_sha256,
        "runtime_sha256": runtime_sha256,
        "agent": dict(plan["agent"]),
        "isolation": dict(plan["isolation"]),
        "replacement_policy": dict(plan["replacement_policy"]),
    }
    if replaces_run_id:
        manifest["replaces_run_id"] = replaces_run_id
    return manifest


def verify_manifest(manifest: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != PHASE08_SCHEMA or manifest.get("schedule_sha256") != plan.get("schedule_sha256"):
        raise ValueError("manifest schema or schedule hash does not match the frozen plan")
    lookup_id = manifest.get("replaces_run_id") or manifest.get("run_id")
    entry = next((item for item in plan.get("schedule", []) if item.get("run_id") == lookup_id), None)
    if not entry:
        raise ValueError("manifest run is not in the frozen schedule")
    for field in ("task_id", "condition", "repetition", "schedule_index", "ground_truth_sha256", "scoring_policy_sha256", "task_prompt_sha256", "system_prompt_sha256"):
        expected = entry.get(field) if field in entry else plan.get(field)
        if field == "schedule_index":
            expected = entry["index"]
        if field == "task_prompt_sha256":
            expected = plan["task_prompt_sha256"][manifest["task_id"]]
        if field in {"ground_truth_sha256", "scoring_policy_sha256", "system_prompt_sha256"}:
            expected = plan[field]
        if manifest.get(field) != expected:
            raise ValueError(f"manifest field {field} does not match frozen plan")


def validate_phase07_gate(root: Path) -> dict[str, Any]:
    """Verify Phase 07's 15 slots, including replacement lineage and hashes."""
    manifests = root / "experiment" / "private" / "run-manifests"
    scores = root / "experiment" / "private" / "scores"
    logs = root / "build" / "phase-07" / "runs"
    slots: list[dict[str, Any]] = []
    missing: list[str] = []
    for task in (f"P0{i}" for i in range(1, 6)):
        for condition in CONDITIONS:
            base = f"{task}-{condition}-R1"
            candidates = [base] + [f"{task}-{condition}-R{i}" for i in (2, 3)]
            scored = next((run for run in candidates if (scores / f"{run}.json").is_file()), None)
            if not scored:
                missing.append(base)
                continue
            score = json.loads((scores / f"{scored}.json").read_text(encoding="utf-8"))
            log = logs / f"{scored}.jsonl"
            manifest = manifests / f"{scored}.json"
            valid = log.is_file() and manifest.is_file() and score.get("log_sha256") == file_sha256(log)
            lineage = None
            if scored != base:
                original_log = logs / f"{base}.jsonl"
                replacement_manifest = json.loads(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
                original_events = load_jsonl(original_log) if original_log.is_file() else []
                lineage = replacement_manifest.get("replaces_run_id") == base and any(event.get("event_type") == "run_invalid" and event.get("replacement_run_id") == scored for event in original_events)
                valid = valid and bool(lineage)
            if not valid:
                missing.append(base + " (hash or replacement lineage invalid)")
            slots.append({"slot": base, "scored_run_id": scored, "replacement": scored != base, "valid": valid})
    return {"schema_version": PHASE08_SCHEMA, "valid": not missing and len(slots) == 15, "slot_count": len(slots), "missing": missing, "slots": slots}


def validate_timeout_gate(evidence: Mapping[str, Any]) -> None:
    if evidence.get("status") == "waived":
        required = {"status", "waived_by", "waived_at", "reason", "acknowledged_limitations"}
        if not required <= set(evidence) or evidence.get("acknowledged_limitations") is not True:
            raise ValueError("timeout gate waiver lacks explicit researcher acknowledgement")
        if not all(isinstance(evidence.get(field), str) and evidence[field].strip() for field in ("waived_by", "waived_at", "reason")):
            raise ValueError("timeout gate waiver requires researcher, timestamp and reason")
        return
    required = {"browser_attachment_verified", "controlled_start", "timeout_seconds", "interrupted_at", "turn_status"}
    if not required <= set(evidence):
        raise ValueError("timeout gate evidence lacks required fields")
    if evidence.get("browser_attachment_verified") is not True or evidence.get("timeout_seconds") != 120 or evidence.get("turn_status") != "interrupted":
        raise ValueError("timeout gate must prove a verified browser attachment and interrupted 120-second turn")


def aggregate_scores(plan: Mapping[str, Any], score_dir: Path, manifest_dir: Path, log_dir: Path) -> dict[str, Any]:
    """Aggregate only valid, hash-matched scored runs; never infer missing runs."""
    valid_rows: list[dict[str, Any]] = []
    invalid = replacements = missing = 0
    for entry in plan.get("schedule", []):
        run_id = str(entry["run_id"])
        # A replacement has its own attempt ID and points back to this fixed
        # slot with replaces_run_id.  It fills the slot without creating a
        # second repetition.
        candidates = [(run_id, score_dir / f"{run_id}.json", manifest_dir / f"{run_id}.json", log_dir / f"{run_id}.jsonl")]
        for candidate_manifest in sorted(manifest_dir.glob("*.json")):
            try:
                candidate = json.loads(candidate_manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if candidate.get("replaces_run_id") == run_id:
                candidate_id = str(candidate.get("run_id"))
                candidates.append((candidate_id, score_dir / f"{candidate_id}.json", candidate_manifest, log_dir / f"{candidate_id}.jsonl"))
        selected = next((item for item in reversed(candidates) if item[1].is_file() and item[2].is_file() and item[3].is_file()), None)
        if selected is None:
            missing += 1
            continue
        selected_id, score_path, manifest_path, log_path = selected
        if not score_path.is_file() or not manifest_path.is_file() or not log_path.is_file():
            missing += 1
            continue
        try:
            score = json.loads(score_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            events = load_jsonl(log_path)
        except (OSError, ValueError, json.JSONDecodeError):
            invalid += 1
            continue
        if score.get("log_sha256") != file_sha256(log_path):
            invalid += 1
            continue
        if any(event.get("event_type") == "run_invalid" and event.get("invalid") is True for event in events):
            invalid += 1
            continue
        row = {**entry, "run_id": selected_id, **{key: score.get(key) for key in ("tool_selection_accuracy", "parameter_accuracy", "task_success", "tool_call_limit_exceeded", "tool_decisions", "scored_parameters", "tool_selection_correct", "parameter_correct", "task_successes", "error_categories")}, "log_sha256": score["log_sha256"], "manifest_sha256": file_sha256(manifest_path)}
        row["replacement"] = bool(manifest.get("replaces_run_id"))
        replacements += int(row["replacement"])
        valid_rows.append(row)
    by_condition: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    by_repetition: dict[str, dict[str, Any]] = {}
    def summarise(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"runs": 0, "tool_selection_accuracy": None, "parameter_accuracy": None, "task_success_rate": None, "tool_selection_correct": 0, "tool_decisions": 0, "parameter_correct": 0, "scored_parameters": 0, "task_successes": 0}
        selection_den = sum(int(row.get("tool_decisions") or 0) for row in rows)
        parameter_den = sum(int(row.get("scored_parameters") or 0) for row in rows)
        successes = sum(int(row.get("task_success") or 0) for row in rows)
        selection_correct = sum(int(row.get("tool_selection_correct") if row.get("tool_selection_correct") is not None else round(float(row.get("tool_selection_accuracy") or 0) * int(row.get("tool_decisions") or 0))) for row in rows)
        parameter_correct = sum(int(row.get("parameter_correct") if row.get("parameter_correct") is not None else round(float(row.get("parameter_accuracy") or 0) * int(row.get("scored_parameters") or 0))) for row in rows)
        return {"runs": len(rows), "tool_selection_accuracy": selection_correct / selection_den if selection_den else 0.0, "parameter_accuracy": parameter_correct / parameter_den if parameter_den else 0.0, "task_success_rate": successes / len(rows), "tool_selection_correct": selection_correct, "tool_decisions": selection_den, "parameter_correct": parameter_correct, "scored_parameters": parameter_den, "task_successes": successes}
    for condition in CONDITIONS:
        by_condition[condition] = summarise([row for row in valid_rows if row["condition"] == condition])
    for task in sorted({str(item["task_id"]) for item in plan.get("schedule", [])}):
        by_task[task] = summarise([row for row in valid_rows if row["task_id"] == task])
    for repetition in (1, 2, 3):
        by_repetition[str(repetition)] = summarise([row for row in valid_rows if row["repetition"] == repetition])
    errors = Counter(error for row in valid_rows for error in (row.get("error_categories") or []))
    return {"schema_version": PHASE08_SCHEMA, "mode": plan.get("mode"), "planned_runs": len(plan.get("schedule", [])), "valid_runs": len(valid_rows), "invalid_runs": invalid, "replacement_runs": replacements, "missing_runs": missing, "by_condition": by_condition, "by_task": by_task, "by_repetition": by_repetition, "error_categories": dict(sorted(errors.items())), "runs": valid_rows}
