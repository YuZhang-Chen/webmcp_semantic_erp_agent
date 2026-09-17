"""CLI for the independent Phase 8 constrained-budget study."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .budget_study import (
    BUDGET_BY_DIFFICULTY,
    BUDGET_PROTOCOL,
    BUDGET_SCHEMA,
    BUDGET_TASKS,
    build_manifest,
    build_plan,
    derive_corpus,
    read_json,
    score_budget_run,
    sha256_value,
    summarize_scores,
    validate_schedule,
    verify_manifest,
    write_json,
)
from .headless import GatewayRuntimeExecutor, OpenAIResponsesAdapter, ReplayExecutor, ToolCallLimitExceeded, catalog_to_openai_tools
from .phase07 import ExperimentLogWriter, file_sha256, load_jsonl, validate_ground_truth, validate_scoring_policy
from .phase08_cli import archive_headless_answer
from .runner import SYSTEM_PROMPT, project_id_only_case

ROOT = Path(__file__).resolve().parents[2]
CATALOG_NAMES = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}
CANDIDATE_NAMES = ("ChatGPT_formal-20-review-draft-v2.json", "Claude_phase08_selection.md", "Gemini_selected_20_cases.json")


def _parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="phase08-budget-experiment")
    commands = root.add_subparsers(dest="command", required=True)

    derive = commands.add_parser("derive-corpus")
    derive.add_argument("--raw-parent", type=Path, required=True)
    derive.add_argument("--sealed-parent", type=Path, required=True)
    derive.add_argument("--candidate-dir", type=Path, required=True)
    derive.add_argument("--freshness-attestation", type=Path, required=True)
    derive.add_argument("--raw-output", type=Path, required=True)
    derive.add_argument("--sealed-output", type=Path, required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--raw-ground-truth", type=Path, required=True)
    prepare.add_argument("--sealed-ground-truth", type=Path, required=True)
    prepare.add_argument("--policy", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)

    manifests = commands.add_parser("make-run-manifests")
    manifests.add_argument("--plan", type=Path, required=True)
    manifests.add_argument("--output-dir", type=Path, required=True)
    manifests.add_argument("--transport", choices=["direct-browser", "local-gateway"], default="local-gateway")
    manifests.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    manifests.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))

    replacement = commands.add_parser("make-replacement-manifest")
    replacement.add_argument("--plan", type=Path, required=True)
    replacement.add_argument("--base-manifest", type=Path, required=True)
    replacement.add_argument("--replacement-run-id", required=True)
    replacement.add_argument("--output", type=Path, required=True)

    check = commands.add_parser("integration-check")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--manifest-dir", type=Path, required=True)
    check.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    check.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    check.add_argument("--output", type=Path)

    batch = commands.add_parser("headless-batch")
    batch.add_argument("--plan", type=Path, required=True)
    batch.add_argument("--manifest-dir", type=Path, required=True)
    batch.add_argument("--config", required=True)
    batch.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    batch.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    batch.add_argument("--output-dir", type=Path, required=True)
    batch.add_argument("--log-dir", type=Path, required=True)
    batch.add_argument("--hmac-key-env", default="HMAC_KEY")

    score = commands.add_parser("score-batch")
    score.add_argument("--plan", type=Path, required=True)
    score.add_argument("--manifest-dir", type=Path, required=True)
    score.add_argument("--log-dir", type=Path, required=True)
    score.add_argument("--raw-ground-truth", type=Path, required=True)
    score.add_argument("--sealed-ground-truth", type=Path, required=True)
    score.add_argument("--policy", type=Path, required=True)
    score.add_argument("--score-dir", type=Path, required=True)
    score.add_argument("--hmac-key-env", default="HMAC_KEY")

    summary = commands.add_parser("summarize")
    summary.add_argument("--plan", type=Path, required=True)
    summary.add_argument("--score-dir", type=Path, required=True)
    summary.add_argument("--manifest-dir", type=Path)
    summary.add_argument("--log-dir", type=Path)
    summary.add_argument("--output", type=Path, required=True)
    return root


def _candidate_hashes(directory: Path) -> dict[str, str]:
    paths = [directory / name for name in CANDIDATE_NAMES]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise ValueError("candidate files missing: " + ", ".join(missing))
    return {path.name: file_sha256(path) for path in paths}


def _load_config(value: str) -> dict[str, Any]:
    if value.startswith(("http://", "https://")):
        with urllib.request.urlopen(value, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    return read_json(Path(value))


def _ordered_manifests(manifest_dir: Path, plan: Mapping[str, Any]) -> list[Path]:
    validate_schedule(plan["schedule"])
    expected = [str(item["run_id"]) for item in plan["schedule"]]
    paths_by_slot: dict[str, Path] = {}
    extra: list[str] = []
    for path in manifest_dir.glob("*.json"):
        manifest = read_json(path)
        slot = str(manifest.get("replaces_run_id") or manifest.get("run_id") or "")
        if slot not in expected or slot in paths_by_slot:
            extra.append(path.stem)
        else:
            paths_by_slot[slot] = path
    missing = sorted(set(expected) - set(paths_by_slot))
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("unexpected=" + ",".join(extra))
        raise ValueError("manifest set does not match frozen schedule (" + "; ".join(detail) + ")")
    paths = []
    for entry in plan["schedule"]:
        path = paths_by_slot[entry["run_id"]]
        manifest = read_json(path)
        verify_manifest(manifest, plan)
        paths.append(path)
    return paths


def _run_one(manifest_path: Path, *, catalog_dir: Path, bindings_path: Path, config: Mapping[str, Any], output: Path, log_path: Path, hmac_key_env: str) -> int:
    manifest = read_json(manifest_path)
    catalog = read_json(catalog_dir / CATALOG_NAMES[manifest["condition"]])
    tools = catalog_to_openai_tools(catalog)
    if not bindings_path.is_file():
        raise ValueError(f"runtime bindings missing: {bindings_path}")
    executor = GatewayRuntimeExecutor(read_json(bindings_path), config)
    provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
    configured_model = os.environ.get("HEADLESS_AGENT_MODEL", "")
    if configured_model != manifest["agent"]["model"]:
        raise ValueError("HEADLESS_AGENT_MODEL must match the manifest model")
    adapter = OpenAIResponsesAdapter(model=None if provider == "azure_openai" else configured_model)
    key = os.environ.get(hmac_key_env, "")
    logger = ExperimentLogWriter(log_path, {**manifest, "execution_mode": "headless-budget", "data_mode": "live", "agent_adapter": adapter.provider}, key)
    sequence = 0
    call_order = 0

    def append(event: Mapping[str, Any]) -> None:
        nonlocal sequence
        sequence += 1
        logger.append({
            "schema_version": "1.0", "run_id": manifest["run_id"], "task_id": manifest["task_id"],
            "condition": manifest["condition"], "repetition": manifest["repetition"], "sequence": sequence,
            "timestamp": datetime.now(UTC).isoformat(), **event,
        })

    append({"event_type": "run_started", "actor": "system"})

    def observe(name: str, operation: str, arguments: Mapping[str, Any], success: bool, result_value: Mapping[str, Any] | None, duration: float, error: Exception | None) -> None:
        nonlocal call_order
        call_order += 1
        category = "tool_budget_exhausted" if isinstance(error, ToolCallLimitExceeded) else "sap_query_error" if error else None
        append({
            "event_type": "tool_call", "actor": "agent", "call_order": call_order,
            "tool_name": name, "canonical_operation": operation, "parameters": dict(arguments),
            "success": success, "executed": not isinstance(error, ToolCallLimitExceeded),
            "duration_ms": round(duration * 1000), "result_summary": dict(result_value) if success and isinstance(result_value, Mapping) else None,
            "error": {"code": "TOOL_CALL_LIMIT_EXCEEDED" if isinstance(error, ToolCallLimitExceeded) else "EXECUTION_FAILED", "message": str(error), "retryable": False} if error else None,
            "error_category": category, "page_state_before": {}, "page_state_after": {},
        })

    try:
        result = adapter.run(SYSTEM_PROMPT, manifest["task_prompt"], tools, executor, condition=manifest["condition"], timeout_seconds=120, tool_call_limit=int(manifest["agent"]["tool_call_limit"]), observer=observe)
        completion = archive_headless_answer(result.answer, output, log_path)
        append({"event_type": "run_completed", "actor": "system", **completion, "termination_reason": "agent_final_answer"})
        return 0
    except ToolCallLimitExceeded as error:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("", encoding="utf-8")
        append({
            "event_type": "run_completed", "actor": "system", "answer_sha256": None, "answer_bytes": 0,
            "raw_answer_file": None, "reported_outcome": {"sales_orders": [], "deliveries": [], "billings": []},
            "answer_parse_error": str(error), "termination_reason": "tool_call_limit_exceeded",
        })
        return 0
    except Exception as error:
        append({"event_type": "run_invalid", "actor": "system", "invalid": True, "reason": str(error)})
        return 1


def _score_one(manifest_path: Path, plan: Mapping[str, Any], events: list[dict[str, Any]], raw: Mapping[str, Any], sealed: Mapping[str, Any], policy: Mapping[str, Any], key: str) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    completed = next((event for event in reversed(events) if event.get("event_type") == "run_completed"), None)
    if not completed:
        raise ValueError("completed run is required before scoring")
    raw_case = next((case for case in raw.get("cases", []) if case.get("task_id") == manifest["task_id"]), None)
    sealed_case = next((case for case in sealed.get("cases", []) if case.get("task_id") == manifest["task_id"]), None)
    if not raw_case or not sealed_case:
        raise ValueError(f"corpus lacks task {manifest['task_id']}")
    projected = project_id_only_case(raw_case, sealed_case, key)
    result = score_budget_run(events, projected, policy, completed.get("reported_outcome", {"sales_orders": [], "deliveries": [], "billings": []}))
    result.update({"run_id": manifest["run_id"], "task_id": manifest["task_id"], "condition": manifest["condition"], "repetition": manifest["repetition"], "manifest_sha256": file_sha256(manifest_path)})
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "derive-corpus":
        if not args.freshness_attestation.is_file():
            example = args.freshness_attestation.with_name("budget-freshness-attestation.example.json")
            raise SystemExit(f"freshness attestation not found: {args.freshness_attestation}. Copy {example} to the requested path, manually confirm all 12 live SAP cases, then set status to confirmed.")
        raw_parent, sealed_parent = read_json(args.raw_parent), read_json(args.sealed_parent)
        hashes = _candidate_hashes(args.candidate_dir)
        attestation = read_json(args.freshness_attestation)
        raw, sealed = derive_corpus(raw_parent, sealed_parent, candidate_hashes=hashes, freshness_attestation=attestation)
        write_json(args.raw_output, raw); write_json(args.sealed_output, sealed)
        print(json.dumps({"raw_output": str(args.raw_output), "sealed_output": str(args.sealed_output), "case_count": 12, "candidate_file_sha256": hashes}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "prepare":
        raw, sealed, policy = read_json(args.raw_ground_truth), read_json(args.sealed_ground_truth), read_json(args.policy)
        validate_ground_truth(sealed, require_approved=True); validate_scoring_policy(policy)
        optional = policy.get("allowed_optional_operations", {})
        if any(optional.get(difficulty, []) for difficulty in ("D1", "D2", "D3")):
            raise SystemExit("constrained-budget policy must have empty optional operations for D1/D2/D3")
        plan = build_plan(raw, sealed, policy_sha256=file_sha256(args.policy), candidate_hashes=raw["derived_from"]["candidate_file_sha256"], freshness_attestation=raw["derived_from"]["freshness_attestation"])
        write_json(args.output, plan); print(json.dumps({"output": str(args.output), "run_count": 72, "schedule_sha256": plan["schedule_sha256"]}, sort_keys=True)); return 0
    if args.command == "make-run-manifests":
        plan = read_json(args.plan); validate_schedule(plan["schedule"]); runtime_sha = read_json(args.bindings).get("artifactSha256", "")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for entry in plan["schedule"]:
            catalog_sha = read_json(args.catalog_dir / CATALOG_NAMES[entry["condition"]]).get("artifactSha256", "")
            write_json(args.output_dir / f"{entry['run_id']}.json", build_manifest(plan, entry, transport=args.transport, catalog_sha256=catalog_sha, runtime_sha256=runtime_sha))
        print(json.dumps({"output_dir": str(args.output_dir), "run_count": 72}, sort_keys=True)); return 0
    if args.command == "make-replacement-manifest":
        plan, base = read_json(args.plan), read_json(args.base_manifest)
        entry = next((item for item in plan["schedule"] if item["run_id"] == base.get("replaces_run_id", base.get("run_id"))), None)
        if not entry or args.replacement_run_id in {item["run_id"] for item in plan["schedule"]}:
            raise SystemExit("invalid base or replacement run ID")
        replacement = build_manifest(plan, entry, transport=base.get("transport", "local-gateway"), catalog_sha256=base.get("catalog_sha256", ""), runtime_sha256=base.get("runtime_sha256", ""), replaces_run_id=entry["run_id"])
        replacement["run_id"] = args.replacement_run_id; replacement["attempt"] = int(base.get("attempt", 1)) + 1
        write_json(args.output, replacement); print(json.dumps({"output": str(args.output), "run_id": args.replacement_run_id}, sort_keys=True)); return 0
    if args.command == "integration-check":
        plan = read_json(args.plan); paths = _ordered_manifests(args.manifest_dir, plan); missing = []
        if not args.bindings.is_file(): missing.append(str(args.bindings))
        catalogs = {}
        for condition, name in CATALOG_NAMES.items():
            path = args.catalog_dir / name
            catalogs[condition] = file_sha256(path) if path.is_file() else None
            if not path.is_file() or len(read_json(path).get("tools", [])) != 4: missing.append(str(path))
        result = {"schema_version": BUDGET_SCHEMA, "protocol": BUDGET_PROTOCOL, "valid": not missing, "run_count": len(paths), "catalogs": catalogs, "missing": missing}
        if args.output: write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0 if result["valid"] else 2
    if args.command == "headless-batch":
        plan = read_json(args.plan); manifests = _ordered_manifests(args.manifest_dir, plan); config = _load_config(args.config); args.output_dir.mkdir(parents=True, exist_ok=True); args.log_dir.mkdir(parents=True, exist_ok=True); failures = []
        for path in manifests:
            code = _run_one(path, catalog_dir=args.catalog_dir, bindings_path=args.bindings, config=config, output=args.output_dir / f"{path.stem}.txt", log_path=args.log_dir / f"{path.stem}.jsonl", hmac_key_env=args.hmac_key_env)
            if code: failures.append(path.stem)
        print(json.dumps({"run_count": len(manifests), "invalid_runs": failures, "output_dir": str(args.output_dir), "log_dir": str(args.log_dir)}, ensure_ascii=False, sort_keys=True)); return 1 if failures else 0
    if args.command == "score-batch":
        plan, raw, sealed, policy = read_json(args.plan), read_json(args.raw_ground_truth), read_json(args.sealed_ground_truth), read_json(args.policy)
        validate_ground_truth(sealed, require_approved=True); validate_scoring_policy(policy); key = os.environ.get(args.hmac_key_env, "")
        if len(key.encode("utf-8")) < 32: raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
        manifests = _ordered_manifests(args.manifest_dir, plan); args.score_dir.mkdir(parents=True, exist_ok=True); scored = []; invalid = []; missing = []
        for manifest_path in manifests:
            log_path = args.log_dir / f"{manifest_path.stem}.jsonl"
            if not log_path.is_file(): missing.append(manifest_path.stem); continue
            events = load_jsonl(log_path)
            if any(event.get("event_type") == "run_invalid" and event.get("invalid") is True for event in events): invalid.append(manifest_path.stem); continue
            result = _score_one(manifest_path, plan, events, raw, sealed, policy, key)
            result["log_sha256"] = file_sha256(log_path)
            write_json(args.score_dir / f"{manifest_path.stem}.json", result); scored.append(manifest_path.stem)
        print(json.dumps({"scored": len(scored), "invalid": invalid, "missing": missing, "score_dir": str(args.score_dir)}, ensure_ascii=False, sort_keys=True)); return 0 if not invalid and not missing else 2
    if args.command == "summarize":
        plan = read_json(args.plan); rows = []
        for path in sorted(args.score_dir.glob("*.json")):
            try: rows.append(read_json(path))
            except (OSError, ValueError, json.JSONDecodeError): continue
        result = summarize_scores(plan, rows)
        scored_ids = {str(row.get("run_id")) for row in rows}
        expected_ids = {str(item["run_id"]) for item in plan["schedule"]}
        result["slot_accounting"] = {"planned": len(expected_ids), "scored": len(scored_ids), "missing_score_slots": sorted(expected_ids - scored_ids), "invalid_slots": [], "replacement_slots": sorted(str(row.get("run_id")) for row in rows if row.get("replaces_run_id"))}
        if args.manifest_dir and args.manifest_dir.is_dir():
            manifests = [read_json(path) for path in args.manifest_dir.glob("*.json")]
            result["slot_accounting"]["replacement_slots"] = sorted(str(item.get("run_id")) for item in manifests if item.get("replaces_run_id"))
        if args.log_dir and args.log_dir.is_dir():
            result["slot_accounting"]["invalid_slots"] = sorted(path.stem for path in args.log_dir.glob("*.jsonl") if any(event.get("event_type") == "run_invalid" and event.get("invalid") is True for event in load_jsonl(path)))
        write_json(args.output, result); print(json.dumps({"output": str(args.output), "valid_runs": len(rows), "planned_runs": 72}, sort_keys=True)); return 0
    raise SystemExit(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
