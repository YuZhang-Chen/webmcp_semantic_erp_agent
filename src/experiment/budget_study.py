"""Planning, validation and scoring for the Phase 8 constrained-budget study.

This module is intentionally independent from the Phase 8 v1 protocol.  It
reuses the approved v1 corpus and the governed runtime, but gives each task a
budget equal to its required operation count so exhaustive querying becomes a
measurable failure mode.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase07 import canonical_bytes, file_sha256, load_jsonl, score_run, validate_ground_truth, validate_scoring_policy
from .phase08 import build_task_prompts
from .runner import ANSWER_KEYS, CONDITIONS, SYSTEM_PROMPT, project_id_only_case

BUDGET_SCHEMA = "phase08-budget-1.0"
BUDGET_PROTOCOL = "phase08-constrained-budget-study"
BUDGET_SEED = 20260916
BUDGET_REPETITIONS = 2
BUDGET_QUOTA = {"D1": 3, "D2": 4, "D3": 5}
BUDGET_BY_DIFFICULTY = {"D1": 1, "D2": 2, "D3": 3}
BUDGET_TASKS = (
    ("F08-T01", "D1"), ("F08-T02", "D1"), ("F08-T03", "D1"),
    ("F08-T05", "D2"), ("F08-T06", "D2"), ("F08-T07", "D2"), ("F08-T08", "D2"),
    ("F08-T13", "D3"), ("F08-T14", "D3"), ("F08-T15", "D3"), ("F08-T16", "D3"), ("F08-T17", "D3"),
)
BUDGET_FALLBACKS = {"D1": ("F08-T04",), "D2": ("F08-T09", "F08-T10", "F08-T11", "F08-T12"), "D3": ("F08-T18", "F08-T19", "F08-T20")}
BOOTSTRAP_SEED = 2026091608
BOOTSTRAP_RESAMPLES = 10000


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _case_identity(case: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        case.get("candidate_id"), case.get("difficulty"), case.get("selection_basis"),
        tuple(sorted((case.get("selected_by") or {}).items())),
        tuple(item.get("operation_id") for item in case.get("required_operations", [])),
    )


def validate_freshness_attestation(attestation: Mapping[str, Any], task_ids: Sequence[str]) -> None:
    required = {"source_id", "researcher", "confirmed_at", "status", "task_ids"}
    if not required <= set(attestation) or attestation.get("source_id") != "webmcp.sap_sd.odata" or attestation.get("status") != "confirmed":
        raise ValueError("freshness attestation must confirm webmcp.sap_sd.odata")
    if not isinstance(attestation.get("researcher"), str) or not attestation["researcher"].strip() or not isinstance(attestation.get("confirmed_at"), str) or not attestation["confirmed_at"].strip():
        raise ValueError("freshness attestation requires researcher and timestamp")
    if set(attestation.get("task_ids", [])) != set(task_ids):
        raise ValueError("freshness attestation task_ids do not match selected cases")


def derive_corpus(
    raw_parent: Mapping[str, Any],
    sealed_parent: Mapping[str, Any],
    *,
    candidate_hashes: Mapping[str, str],
    freshness_attestation: Mapping[str, Any],
    selected_source_tasks: Sequence[str] = tuple(task for task, _ in BUDGET_TASKS),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive a 12-case corpus without using v1 outcomes to choose cases."""
    selected_source_tasks = tuple(selected_source_tasks)
    if len(selected_source_tasks) != 12 or len(set(selected_source_tasks)) != 12:
        raise ValueError("constrained study requires twelve distinct source tasks")
    expected_difficulties = dict(BUDGET_TASKS)
    if set(selected_source_tasks) != set(expected_difficulties):
        raise ValueError("selected source tasks do not match the frozen outcome-independent roster")
    validate_ground_truth(raw_parent, require_approved=False)
    validate_ground_truth(sealed_parent, require_approved=True)
    if sealed_parent.get("source_id") != "webmcp.sap_sd.odata" or raw_parent.get("source_id") != "webmcp.sap_sd.odata":
        raise ValueError("parent corpus must use webmcp.sap_sd.odata")
    raw_cases = {str(case["task_id"]): case for case in raw_parent.get("cases", [])}
    sealed_cases = {str(case["task_id"]): case for case in sealed_parent.get("cases", [])}
    validate_freshness_attestation(freshness_attestation, selected_source_tasks)
    raw_out: list[dict[str, Any]] = []
    sealed_out: list[dict[str, Any]] = []
    for index, source_task in enumerate(selected_source_tasks, 1):
        raw_case, sealed_case = raw_cases.get(source_task), sealed_cases.get(source_task)
        if not raw_case or not sealed_case or _case_identity(raw_case) != _case_identity(sealed_case):
            raise ValueError(f"raw/sealed parent mismatch for {source_task}")
        difficulty = expected_difficulties[source_task]
        if raw_case.get("difficulty") != difficulty or sealed_case.get("difficulty") != difficulty:
            raise ValueError(f"difficulty mismatch for {source_task}")
        new_id = f"CB08-T{index:02d}"
        raw_case = deepcopy(raw_case)
        sealed_case = deepcopy(sealed_case)
        raw_case["task_id"] = new_id
        sealed_case["task_id"] = new_id
        raw_case["source_task_id"] = source_task
        sealed_case["source_task_id"] = source_task
        raw_out.append(raw_case)
        sealed_out.append(sealed_case)
    parent_hashes = {"raw": sha256_value(raw_parent), "sealed": sha256_value(sealed_parent)}
    provenance = {
        "source_id": "webmcp.sap_sd.odata",
        "selection_rule": "fixed outcome-independent roster: agreement-priority selection, then frozen Phase 8 v1 order",
        "selected_source_tasks": list(selected_source_tasks),
        "parent_corpus_sha256": parent_hashes,
        "candidate_file_sha256": dict(sorted(candidate_hashes.items())),
        "freshness_attestation": dict(freshness_attestation),
    }
    common = {
        "schema_version": "1.0",
        "corpus_id": "sap-sd-phase08-constrained-budget-v1",
        "source_id": "webmcp.sap_sd.odata",
        "review_protocol": "human_only",
        "quota": dict(BUDGET_QUOTA),
        "derived_from": provenance,
    }
    raw = {**common, "classification": "researcher_private_raw_ground_truth", "cases": raw_out}
    sealed = {**common, "classification": "ground_truth", "cases": sealed_out}
    return raw, sealed


def build_schedule(*, seed: int = BUDGET_SEED) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    task_ids = [task for task, _ in BUDGET_TASKS]
    permutations = list(itertools.permutations(CONDITIONS))
    schedule: list[dict[str, Any]] = []
    for repetition in range(1, BUDGET_REPETITIONS + 1):
        ordered_tasks = list(task_ids)
        rng.shuffle(ordered_tasks)
        order_pool = permutations * (len(ordered_tasks) // len(permutations))
        rng.shuffle(order_pool)
        for task_id, order in zip(ordered_tasks, order_pool):
            for condition in order:
                schedule.append({
                    "index": len(schedule) + 1,
                    "task_id": f"CB08-T{task_ids.index(task_id) + 1:02d}",
                    "source_task_id": task_id,
                    "condition": condition,
                    "repetition": repetition,
                    "run_id": f"CB08-T{task_ids.index(task_id) + 1:02d}-{condition}-R{repetition}",
                })
    return schedule


def validate_schedule(schedule: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_tasks = {f"CB08-T{i:02d}" for i in range(1, 13)}
    if len(schedule) != 72:
        raise ValueError("constrained-budget schedule must contain 72 runs")
    if len({item.get("run_id") for item in schedule}) != 72:
        raise ValueError("schedule run IDs must be unique")
    slots = Counter((item.get("task_id"), item.get("condition"), item.get("repetition")) for item in schedule)
    if set(task for task, _, _ in slots) != expected_tasks or any(count != 1 for count in slots.values()):
        raise ValueError("every task × condition × repetition slot must occur exactly once")
    condition_counts = Counter(item.get("condition") for item in schedule)
    if condition_counts != Counter({"A": 24, "B": 24, "C": 24}):
        raise ValueError("conditions must each contain 24 runs")
    orders = Counter()
    for start in range(0, len(schedule), 3):
        block = schedule[start:start + 3]
        if len(block) != 3 or len({item.get("task_id") for item in block}) != 1:
            raise ValueError("schedule must use three-condition task blocks")
        orders[tuple(item.get("condition") for item in block)] += 1
    if len(orders) != 6 or any(count != 4 for count in orders.values()):
        raise ValueError("the six A/B/C orders must each occur exactly four times")
    return {"valid": True, "run_count": 72, "task_count": 12, "condition_counts": dict(condition_counts), "condition_order_counts": {"".join(key): value for key, value in sorted(orders.items())}}


def build_plan(raw_corpus: Mapping[str, Any], sealed_corpus: Mapping[str, Any], *, policy_sha256: str, candidate_hashes: Mapping[str, str], freshness_attestation: Mapping[str, Any], seed: int = BUDGET_SEED) -> dict[str, Any]:
    validate_ground_truth(raw_corpus, require_approved=False)
    validate_ground_truth(sealed_corpus, require_approved=True)
    if raw_corpus.get("corpus_id") != sealed_corpus.get("corpus_id") or raw_corpus.get("source_id") != "webmcp.sap_sd.odata" or sealed_corpus.get("source_id") != "webmcp.sap_sd.odata":
        raise ValueError("raw and sealed constrained corpora must share the governed SAP source and corpus ID")
    cases = list(raw_corpus.get("cases", []))
    if len(cases) != 12:
        raise ValueError("constrained corpus must contain 12 cases")
    prompts = build_task_prompts(raw_corpus)
    difficulty_by_task = {str(case["task_id"]): str(case["difficulty"]) for case in cases}
    schedule = build_schedule(seed=seed)
    validate_schedule(schedule)
    task_budgets = {task: BUDGET_BY_DIFFICULTY[difficulty] for task, difficulty in difficulty_by_task.items()}
    plan = {
        "schema_version": BUDGET_SCHEMA,
        "protocol": BUDGET_PROTOCOL,
        "mode": "supplementary",
        "seed": seed,
        "source_id": "webmcp.sap_sd.odata",
        "corpus_id": sealed_corpus.get("corpus_id"),
        "parent_corpus_sha256": raw_corpus.get("derived_from", {}).get("parent_corpus_sha256", {}),
        "candidate_file_sha256": dict(sorted(candidate_hashes.items())),
        "freshness_attestation": dict(freshness_attestation),
        "selection_rule": raw_corpus.get("derived_from", {}).get("selection_rule"),
        "ground_truth_sha256": sha256_value(sealed_corpus),
        "raw_ground_truth_sha256": sha256_value(raw_corpus),
        "scoring_policy_sha256": policy_sha256,
        "task_prompt_sha256": {task: prompts[task]["sha256"] for task in sorted(prompts)},
        "tasks": prompts,
        "task_difficulty": difficulty_by_task,
        "task_budgets": task_budgets,
        "system_prompt": SYSTEM_PROMPT,
        "system_prompt_sha256": sha256_value(SYSTEM_PROMPT),
        "agent": {"provider": "azure_openai", "model": "gpt-5.6-sol", "reasoning": "medium", "temperature": None, "timeout_seconds": 120, "fresh_session_per_run": True},
        "budget_policy": "exact_required_operations",
        "isolation": {"fresh_session_per_run": True, "allow_repository_access": False, "allow_ground_truth_access": False, "allow_scorer_access": False},
        "replacement_policy": {"max_replacements": 2, "invalid_runs_are_not_scored": True, "preserve_original": True, "budget_exhaustion_is_valid_failure": True},
        "answer_schema": {"type": "object", "additionalProperties": False, "required": list(ANSWER_KEYS)},
        "schedule": schedule,
    }
    plan["schedule_sha256"] = sha256_value(schedule)
    return plan


def build_manifest(plan: Mapping[str, Any], entry: Mapping[str, Any], *, transport: str = "local-gateway", catalog_sha256: str = "", runtime_sha256: str = "", replaces_run_id: str | None = None) -> dict[str, Any]:
    task_id = str(entry["task_id"])
    manifest = {
        "schema_version": BUDGET_SCHEMA,
        "protocol": BUDGET_PROTOCOL,
        "mode": "supplementary",
        "source_id": plan["source_id"],
        "corpus_id": plan["corpus_id"],
        "run_id": entry["run_id"],
        "task_id": task_id,
        "source_task_id": entry["source_task_id"],
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
        "agent": {**plan["agent"], "tool_call_limit": plan["task_budgets"][task_id]},
        "budget_policy": plan["budget_policy"],
        "isolation": dict(plan["isolation"]),
        "replacement_policy": dict(plan["replacement_policy"]),
    }
    if replaces_run_id:
        manifest["replaces_run_id"] = replaces_run_id
    return manifest


def verify_manifest(manifest: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != BUDGET_SCHEMA or manifest.get("schedule_sha256") != plan.get("schedule_sha256"):
        raise ValueError("manifest schema or schedule hash does not match constrained plan")
    lookup = manifest.get("replaces_run_id") or manifest.get("run_id")
    entry = next((item for item in plan.get("schedule", []) if item.get("run_id") == lookup), None)
    if not entry:
        raise ValueError("manifest run is not in constrained schedule")
    expected = build_manifest(plan, entry, transport=manifest.get("transport", "local-gateway"), catalog_sha256=manifest.get("catalog_sha256", ""), runtime_sha256=manifest.get("runtime_sha256", ""), replaces_run_id=manifest.get("replaces_run_id"))
    for field in ("task_id", "source_task_id", "condition", "repetition", "schedule_index", "ground_truth_sha256", "scoring_policy_sha256", "task_prompt_sha256", "system_prompt_sha256", "budget_policy"):
        if manifest.get(field) != expected.get(field):
            raise ValueError(f"manifest field {field} does not match constrained plan")
    if manifest.get("agent", {}).get("tool_call_limit") != expected["agent"]["tool_call_limit"]:
        raise ValueError("manifest task-specific tool_call_limit does not match difficulty")


def _required_operation_ids(case: Mapping[str, Any]) -> list[str]:
    return [str(item["operation_id"]) for item in case.get("required_operations", [])]


def _first_choice_ok(difficulty: str, operation: str, required: Sequence[str]) -> bool:
    if difficulty == "D1":
        return operation == "get_sales_order"
    if difficulty == "D2":
        return operation in {"get_related_deliveries", "get_related_billing_documents"} and operation in required
    return operation == "search_sales_orders"


def score_budget_run(events: Sequence[Mapping[str, Any]], case: Mapping[str, Any], policy: Mapping[str, Any], reported_outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Score normal Phase 07 metrics plus constrained-budget metrics."""
    result = score_run(events, case, policy, reported_outcome)
    calls = [event for event in events if event.get("event_type") == "tool_call" and event.get("actor") == "agent"]
    required = _required_operation_ids(case)
    remaining = list(required)
    non_required = duplicates = 0
    successful_required: list[str] = []
    for call in calls:
        operation = str(call.get("canonical_operation", ""))
        if operation in remaining:
            remaining.remove(operation)
            if call.get("success") is True:
                successful_required.append(operation)
        else:
            non_required += 1
            if operation in required:
                duplicates += 1
    first = calls[0].get("canonical_operation") if calls else None
    difficulty = str(case.get("difficulty"))
    termination = next((event.get("termination_reason") for event in reversed(events) if event.get("event_type") == "run_completed"), None)
    exhausted = termination == "tool_call_limit_exceeded" or bool(result.get("tool_call_limit_exceeded"))
    result.update({
        "task_success_under_budget": int(bool(result.get("task_success")) and not exhausted),
        "first_choice_accuracy": int(bool(first) and _first_choice_ok(difficulty, str(first), required)),
        "minimal_tool_set_success": int(bool(result.get("task_success")) and not exhausted and non_required == 0 and duplicates == 0 and len(calls) == len(required)),
        "excess_call_count": non_required,
        "excess_call_rate": non_required / len(calls) if calls else 0.0,
        "budget_exhausted": int(exhausted),
        # The observer records rejected over-budget attempts as ``executed=False``.
        # Older/replayed logs do not have that field, so missing means executed.
        "executed_tool_calls": sum(1 for call in calls if call.get("executed", True) is True),
        "attempted_tool_calls": len(calls),
    })
    if exhausted:
        result["error_categories"] = sorted(set(result.get("error_categories", [])) | {"tool_budget_exhausted"})
    return result


def summarize_scores(plan: Mapping[str, Any], scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(scores)
    def aggregate(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"runs": 0, "task_success_under_budget": None, "first_choice_accuracy": None, "minimal_tool_set_success": None, "parameter_accuracy": None, "budget_exhaustion_rate": None, "excess_call_rate": None, "appendix_decision_micro_tool_selection_accuracy": None, "appendix_decision_micro_parameter_accuracy": None}
        return {
            "runs": len(items),
            "task_success_under_budget": sum(int(x.get("task_success_under_budget", 0)) for x in items) / len(items),
            "first_choice_accuracy": sum(int(x.get("first_choice_accuracy", 0)) for x in items) / len(items),
            "minimal_tool_set_success": sum(int(x.get("minimal_tool_set_success", 0)) for x in items) / len(items),
            "parameter_accuracy": sum(float(x.get("parameter_accuracy", 0.0)) for x in items) / len(items),
            "budget_exhaustion_rate": sum(int(x.get("budget_exhausted", 0)) for x in items) / len(items),
            "excess_call_rate": sum(float(x.get("excess_call_rate", 0.0)) for x in items) / len(items),
            "appendix_decision_micro_tool_selection_accuracy": (sum(int(x.get("tool_selection_correct", 0)) for x in items) / sum(int(x.get("tool_decisions", 0)) for x in items)) if sum(int(x.get("tool_decisions", 0)) for x in items) else None,
            "appendix_decision_micro_parameter_accuracy": (sum(int(x.get("parameter_correct", 0)) for x in items) / sum(int(x.get("scored_parameters", 0)) for x in items)) if sum(int(x.get("scored_parameters", 0)) for x in items) else None,
        }
    by_condition = {condition: aggregate([x for x in rows if x.get("condition") == condition]) for condition in CONDITIONS}
    by_difficulty = {difficulty: aggregate([x for x in rows if plan.get("task_difficulty", {}).get(x.get("task_id")) == difficulty]) for difficulty in BUDGET_QUOTA}
    by_repetition = {str(rep): aggregate([x for x in rows if x.get("repetition") == rep]) for rep in range(1, BUDGET_REPETITIONS + 1)}
    return {"schema_version": BUDGET_SCHEMA, "protocol": BUDGET_PROTOCOL, "mode": "supplementary", "planned_runs": 72, "valid_runs": len(rows), "by_condition": by_condition, "by_difficulty": by_difficulty, "by_repetition": by_repetition, "paired_comparisons": paired_comparisons(rows), "runs": rows}


def _exact_mcnemar(a: Sequence[int], b: Sequence[int]) -> dict[str, Any]:
    wins_a = sum(int(x == 1 and y == 0) for x, y in zip(a, b))
    wins_b = sum(int(x == 0 and y == 1) for x, y in zip(a, b))
    discordant = wins_a + wins_b
    if discordant == 0:
        p_value = 1.0
    else:
        tail = sum(__import__("math").comb(discordant, k) for k in range(min(wins_a, wins_b) + 1)) / (2 ** discordant)
        p_value = min(1.0, 2.0 * tail)
    return {"a_wins": wins_a, "b_wins": wins_b, "discordant": discordant, "p_value": p_value}


def _cluster_bootstrap(rows: Sequence[Mapping[str, Any]], metric: str, a: str, b: str, *, seed: int = BOOTSTRAP_SEED, resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        task = str(row.get("task_id")); condition = str(row.get("condition"))
        if condition in {a, b}:
            grouped.setdefault(task, {}).setdefault(condition, []).append(float(row.get(metric, 0)))
    clusters = [(sum(values.get(a, [0])) / len(values.get(a, [0])), sum(values.get(b, [0])) / len(values.get(b, [0]))) for values in grouped.values() if a in values and b in values]
    if not clusters:
        return {"estimate": None, "ci95": [None, None], "clusters": 0, "seed": seed, "resamples": resamples}
    estimate = sum(x - y for x, y in clusters) / len(clusters)
    rng = random.Random(seed)
    samples: list[float] = []
    for _ in range(resamples):
        draw = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        samples.append(sum(x - y for x, y in draw) / len(draw))
    samples.sort()
    low, high = samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))]
    return {"estimate": estimate, "ci95": [low, high], "clusters": len(clusters), "seed": seed, "resamples": resamples}


def paired_comparisons(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return paired McNemar tests and task-cluster bootstrap intervals."""
    metrics = ("task_success_under_budget", "first_choice_accuracy")
    comparisons: list[dict[str, Any]] = []
    for metric in metrics:
        for a, b in (("A", "B"), ("A", "C"), ("B", "C")):
            paired: dict[tuple[str, Any], dict[str, int]] = {}
            for row in rows:
                key = (str(row.get("task_id")), row.get("repetition"))
                if row.get("condition") in {a, b}:
                    paired.setdefault(key, {})[str(row["condition"])] = int(row.get(metric, 0))
            complete = [pair for pair in paired.values() if a in pair and b in pair]
            mcnemar = _exact_mcnemar([pair[a] for pair in complete], [pair[b] for pair in complete])
            comparisons.append({"metric": metric, "a": a, "b": b, "n_pairs": len(complete), "absolute_percentage_point_difference": (sum(pair[a] - pair[b] for pair in complete) / len(complete) * 100) if complete else None, "mcnemar": mcnemar, "bootstrap": _cluster_bootstrap(rows, metric, a, b)})
    ordered = sorted(comparisons, key=lambda item: item["mcnemar"]["p_value"])
    m = len(ordered)
    running = 0.0
    for index, item in enumerate(ordered):
        adjusted = min(1.0, max(running, (m - index) * item["mcnemar"]["p_value"]))
        running = adjusted
        item["holm_adjusted_p_value"] = adjusted
    return comparisons
