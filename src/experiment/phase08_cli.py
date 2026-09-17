"""Command line interface for the independent Phase 08 experiment workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from .cli import main as phase07_main
from .monthly_candidates import scan_month, summarize_months
from .phase07 import ExperimentLogWriter, file_sha256
from .phase08 import (
    FORMAL_QUOTA,
    MODEL_DEFAULT,
    PHASE08_SEED,
    REASONING_DEFAULT,
    TIMEOUT_DEFAULT,
    TOOL_CALL_LIMIT_DEFAULT,
    aggregate_scores,
    build_manifest,
    build_plan,
    sha256_value,
    validate_phase07_gate,
    validate_phase08_corpus,
    validate_schedule,
    validate_timeout_gate,
    verify_manifest,
)
from .headless import GatewayRuntimeExecutor, OpenAIResponsesAdapter, ReplayExecutor, catalog_to_openai_tools
from .runner import SYSTEM_PROMPT, parse_reported_outcome


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ordered_batch_manifests(manifest_dir: Path, plan: dict) -> list[Path]:
    """Return scheduled manifests in frozen-plan order and reject drift."""
    validate_schedule(plan.get("schedule", []), plan["mode"])
    expected_ids = [str(entry["run_id"]) for entry in plan["schedule"]]
    expected = set(expected_ids)
    actual = {path.stem for path in manifest_dir.glob("*.json")}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing manifests: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected manifests: {', '.join(unexpected)}")
        raise ValueError("headless batch manifest set does not match frozen plan; " + "; ".join(details))
    paths: list[Path] = []
    for run_id in expected_ids:
        path = manifest_dir / f"{run_id}.json"
        manifest = read_json(path)
        verify_manifest(manifest, plan)
        if manifest.get("run_id") != run_id:
            raise ValueError(f"manifest identity does not match filename: {path}")
        paths.append(path)
    return paths


def archive_headless_answer(answer: str, output_path: Path, log_path: Path) -> dict:
    """Persist the exact answer and build the Phase 07-compatible completion fields."""
    answer_bytes = answer.encode("utf-8")
    raw_copy = log_path.with_name(f"{log_path.stem}.answer.raw")
    if raw_copy.exists():
        raise ValueError(f"raw answer archive already exists: {raw_copy}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_copy.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(answer_bytes)
    raw_copy.write_bytes(answer_bytes)
    try:
        reported = parse_reported_outcome(output_path)
        parse_error = None
    except ValueError as exc:
        reported = {"sales_orders": [], "deliveries": [], "billings": []}
        parse_error = str(exc)
    return {
        "answer_sha256": hashlib.sha256(answer_bytes).hexdigest(),
        "answer_bytes": len(answer_bytes),
        "raw_answer_file": raw_copy.name,
        "reported_outcome": reported,
        "answer_parse_error": parse_error,
    }


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="phase08-experiment")
    commands = root.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="freeze a Phase 08 pilot or formal plan")
    prepare.add_argument("--mode", choices=["pilot", "formal"], required=True)
    prepare.add_argument("--ground-truth", type=Path, required=True)
    prepare.add_argument("--raw-ground-truth", type=Path, required=True)
    prepare.add_argument("--policy", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seed", type=int, default=PHASE08_SEED)
    prepare.add_argument("--model", default=MODEL_DEFAULT)
    prepare.add_argument("--reasoning", default=REASONING_DEFAULT)
    prepare.add_argument("--timeout-seconds", type=int, default=TIMEOUT_DEFAULT)
    prepare.add_argument("--tool-call-limit", type=int, default=TOOL_CALL_LIMIT_DEFAULT)

    validate = commands.add_parser("validate-corpus")
    validate.add_argument("--mode", choices=["pilot", "formal"], required=True)
    validate.add_argument("--ground-truth", type=Path, required=True)
    validate.add_argument("--raw-ground-truth", type=Path)

    monthly = commands.add_parser("scan-month", help="discover 2026 SAP candidates one month at a time (GET only)")
    monthly.add_argument("--month", required=True, help="2026-MM")
    monthly.add_argument("--private-dir", type=Path, default=Path("experiment/private/phase08"))
    monthly.add_argument("--env", type=Path, default=Path(".env"))
    monthly.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    monthly.add_argument("--limit", type=int, default=30)
    monthly.add_argument("--delay-ms", type=int, default=100)

    candidate_status = commands.add_parser("candidate-status", help="show counts and hashes without SAP business identifiers")
    candidate_status.add_argument("--private-dir", type=Path, default=Path("experiment/private/phase08"))

    manifests = commands.add_parser("make-run-manifests")
    manifests.add_argument("--plan", type=Path, required=True)
    manifests.add_argument("--output-dir", type=Path, required=True)
    manifests.add_argument("--transport", choices=["direct-browser", "local-gateway"], default="local-gateway")
    manifests.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    manifests.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))

    replacement = commands.add_parser("make-replacement-manifest", help="create an independent replacement attempt for an invalid slot")
    replacement.add_argument("--plan", type=Path, required=True)
    replacement.add_argument("--base-manifest", type=Path, required=True)
    replacement.add_argument("--replacement-run-id", required=True)
    replacement.add_argument("--output", type=Path, required=True)

    integration = commands.add_parser("integration-check")
    integration.add_argument("--plan", type=Path, required=True)
    integration.add_argument("--frontend-root", type=Path, default=Path("frontend/dist"))
    integration.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    integration.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    integration.add_argument("--timeout-evidence", type=Path)
    integration.add_argument("--output", type=Path)

    gate = commands.add_parser("verify-phase07-gate")
    gate.add_argument("--root", type=Path, default=Path("."))
    gate.add_argument("--output", type=Path)

    timeout = commands.add_parser("verify-timeout-gate")
    timeout.add_argument("--evidence", type=Path, required=True)

    summary = commands.add_parser("summarize")
    summary.add_argument("--plan", type=Path, required=True)
    summary.add_argument("--score-dir", type=Path, required=True)
    summary.add_argument("--manifest-dir", type=Path, required=True)
    summary.add_argument("--log-dir", type=Path, required=True)
    summary.add_argument("--output", type=Path)

    serve = commands.add_parser("serve", help="serve one Phase 08 manifest with the shared Phase 07 workbench")
    serve.add_argument("--run-manifest", type=Path, required=True)
    serve.add_argument("--host", default="localhost")
    serve.add_argument("--port", type=int, default=5173)
    serve.add_argument("--frontend-root", type=Path, default=Path("frontend/dist"))
    serve.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    serve.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    serve.add_argument("--env", type=Path, default=Path(".env"))
    serve.add_argument("--log-dir", type=Path, default=Path("build/phase-08/runs"))

    headless_check = commands.add_parser("headless-check", help="validate headless tool-calling prerequisites")
    headless_check.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    headless_check.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    headless_check.add_argument("--model", default=None)

    headless_run = commands.add_parser("headless-run", help="run one headless tool-calling manifest")
    headless_run.add_argument("--run-manifest", type=Path, required=True)
    headless_run.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    headless_run.add_argument("--config", required=True, help="public runtime config JSON path or URL")
    headless_run.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    headless_run.add_argument("--replay", type=Path, help="private replay records JSON; mutually exclusive with live gateway")
    headless_run.add_argument("--output", type=Path, required=True)
    headless_run.add_argument("--log", type=Path, default=None)
    headless_run.add_argument("--hmac-key-env", default="HMAC_KEY")

    headless_batch = commands.add_parser("headless-batch", help="run a sequence of headless manifests")
    headless_batch.add_argument("--plan", type=Path, required=True, help="frozen Phase 08 plan that defines execution order")
    headless_batch.add_argument("--manifest-dir", type=Path, required=True)
    headless_batch.add_argument("--config", required=True)
    headless_batch.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    headless_batch.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    headless_batch.add_argument("--output-dir", type=Path, required=True)
    headless_batch.add_argument("--log-dir", type=Path, default=Path("build/phase-08/headless-runs"))
    headless_batch.add_argument("--hmac-key-env", default="HMAC_KEY")

    # Run lifecycle commands use the exact Phase 07 append-only log and answer
    # validation implementation.  Dispatching keeps the event schema aligned.
    for name in ("close-run", "verify-log", "record-intervention"):
        command = commands.add_parser(name, help=f"Phase 07-compatible {name} for a Phase 08 run")
        if name == "close-run":
            command.add_argument("--log", type=Path, required=True)
            command.add_argument("--answer-file", type=Path, required=True)
            command.add_argument("--reported-outcome", type=Path)
            command.add_argument("--hmac-key-env", default="HMAC_KEY")
        elif name == "verify-log":
            command.add_argument("--log", type=Path, required=True)
        else:
            command.add_argument("--log", type=Path, required=True)
            command.add_argument("--type", required=True, choices=["authentication", "authorization", "start", "environment_repair", "decision_guidance"])
            command.add_argument("--operator", required=True)
            command.add_argument("--invalid", action="store_true")
            command.add_argument("--note", default="")
            command.add_argument("--replacement-run-id")
            command.add_argument("--hmac-key-env", default="HMAC_KEY")
            command.add_argument("--output", type=Path)
    return root


def _integration(plan: dict, frontend_root: Path, catalog_dir: Path, bindings: Path, timeout_evidence: Path | None) -> dict:
    missing = [str(path) for path in (frontend_root / "index.html", bindings) if not path.is_file()]
    names = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}
    catalogs: dict[str, str | None] = {}
    counts: dict[str, int | None] = {}
    for condition, name in names.items():
        path = catalog_dir / name
        catalogs[condition] = file_sha256(path) if path.is_file() else None
        counts[condition] = None
        if not path.is_file():
            missing.append(str(path))
            continue
        try:
            counts[condition] = len(read_json(path).get("tools", []))
        except (OSError, ValueError, json.JSONDecodeError):
            counts[condition] = 0
        if counts[condition] != 4:
            missing.append(f"{condition} catalog must expose exactly four Site Tools")
    if plan.get("agent", {}).get("model") != MODEL_DEFAULT or plan.get("agent", {}).get("reasoning") != REASONING_DEFAULT or plan.get("agent", {}).get("timeout_seconds") != TIMEOUT_DEFAULT or plan.get("agent", {}).get("tool_call_limit") != TOOL_CALL_LIMIT_DEFAULT:
        missing.append("agent settings must be gpt-5.6-sol / medium / 120 seconds / 8 calls")
    try:
        schedule = validate_schedule(plan.get("schedule", []), plan["mode"])
    except ValueError as exc:
        missing.append(str(exc))
        schedule = {"valid": False}
    timeout_status = "not-supplied"
    if timeout_evidence:
        try:
            validate_timeout_gate(read_json(timeout_evidence))
            timeout_status = "waived" if read_json(timeout_evidence).get("status") == "waived" else "verified"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            missing.append(f"timeout gate: {exc}")
            timeout_status = "invalid"
    else:
        missing.append("timeout gate evidence is required before Phase 08 execution")
    return {"schema_version": "phase08-1.0", "valid": not missing, "mode": plan.get("mode"), "required_site_tools": 4, "catalogs": catalogs, "catalog_tool_counts": counts, "schedule": schedule, "timeout_gate": timeout_status, "missing": missing}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "headless-check":
        names = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}
        counts = {}
        for condition, name in names.items():
            catalog = read_json(args.catalog_dir / name)
            counts[condition] = len(catalog_to_openai_tools(catalog))
        if not args.bindings.is_file():
            raise SystemExit(f"runtime bindings missing: {args.bindings}")
        provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
        model = args.model or os.environ.get("HEADLESS_AGENT_MODEL", "")
        provider_ready = bool(os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT") and os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")) if provider == "azure_openai" else bool(os.environ.get("OPENAI_API_KEY"))
        print(json.dumps({"valid": all(value == 4 for value in counts.values()), "catalog_tool_counts": counts, "provider": provider, "provider_configured": provider_ready, "model_configured": bool(model), "ground_truth_loaded": False}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "headless-run":
        manifest = read_json(args.run_manifest)
        names = {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}
        catalog = read_json(args.catalog_dir / names[manifest["condition"]])
        tools = catalog_to_openai_tools(catalog)
        if str(args.config).startswith(("http://", "https://")):
            with urllib.request.urlopen(args.config, timeout=10) as response:
                config = json.loads(response.read().decode("utf-8"))
        else:
            config = read_json(Path(args.config))
        if args.replay:
            executor = ReplayExecutor(read_json(args.replay))
        else:
            executor = GatewayRuntimeExecutor(read_json(args.bindings), config)
        provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
        configured_model = os.environ.get("HEADLESS_AGENT_MODEL", "")
        if not configured_model or configured_model != manifest["agent"]["model"]:
            raise SystemExit("HEADLESS_AGENT_MODEL must be set and match the manifest model")
        adapter = OpenAIResponsesAdapter(model=None if provider == "azure_openai" else configured_model)
        log_path = args.log or Path("build/phase-08/headless-runs") / f"{manifest['run_id']}.jsonl"
        key = os.environ.get(args.hmac_key_env, "")
        log_manifest = {**manifest, "execution_mode": "headless", "data_mode": "replay" if args.replay else "live", "agent_adapter": adapter.provider}
        logger = ExperimentLogWriter(log_path, log_manifest, key)
        raw_copy = log_path.with_name(f"{log_path.stem}.answer.raw")
        if raw_copy.exists():
            raise SystemExit(f"raw answer archive already exists: {raw_copy}")
        sequence = 0
        def append(event):
            nonlocal sequence
            sequence += 1
            logger.append({"schema_version": "1.0", "run_id": manifest["run_id"], "task_id": manifest["task_id"], "condition": manifest["condition"], "repetition": manifest["repetition"], "sequence": sequence, "timestamp": datetime.now(UTC).isoformat(), **event})
        append({"event_type": "run_started", "actor": "system"})
        def observe(name, operation, arguments, success, result_value, duration, error):
            append({"event_type": "tool_call", "actor": "agent", "call_order": sequence, "tool_name": name, "canonical_operation": operation, "parameters": dict(arguments), "success": success, "duration_ms": round(duration * 1000), "result_summary": dict(result_value) if success and isinstance(result_value, Mapping) else None, "error": {"code": "EXECUTION_FAILED", "message": str(error), "retryable": False} if error else None, "error_category": "sap_query_error" if error else None, "page_state_before": {}, "page_state_after": {}})
        try:
            result = adapter.run(SYSTEM_PROMPT, manifest["task_prompt"], tools, executor, condition=manifest["condition"], timeout_seconds=int(manifest["agent"]["timeout_seconds"]), tool_call_limit=int(manifest["agent"]["tool_call_limit"]), observer=observe)
            completion = archive_headless_answer(result.answer, args.output, log_path)
            append({"event_type": "run_completed", "actor": "system", **completion})
        except Exception as error:
            append({"event_type": "run_invalid", "actor": "system", "invalid": True, "reason": str(error)})
            raise
        print(json.dumps({"run_id": manifest["run_id"], "output": str(args.output), "tool_calls": result.tool_calls, "elapsed_seconds": result.elapsed_seconds, "provider": result.provider, "model": result.model}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "headless-batch":
        try:
            manifests = ordered_batch_manifests(args.manifest_dir, read_json(args.plan))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise SystemExit(str(exc)) from exc
        for manifest in manifests:
            main(["headless-run", "--run-manifest", str(manifest), "--catalog-dir", str(args.catalog_dir), "--config", args.config, "--bindings", str(args.bindings), "--output", str(args.output_dir / f"{manifest.stem}.txt"), "--log", str(args.log_dir / f"{manifest.stem}.jsonl"), "--hmac-key-env", args.hmac_key_env])
        print(json.dumps({"run_count": len(manifests), "output_dir": str(args.output_dir), "log_dir": str(args.log_dir)}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command in {"scan-month", "candidate-status"}:
        private_root = Path("experiment/private").resolve()
        selected = args.private_dir.resolve()
        if private_root not in selected.parents:
            raise SystemExit("monthly SAP candidate artifacts must stay under experiment/private/")
        if args.command == "scan-month":
            result = scan_month(args.month, private_dir=selected, env=args.env, bindings=args.bindings, limit=args.limit, delay_ms=args.delay_ms)
        else:
            result = summarize_months(selected)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "prepare":
        corpus, raw, policy = read_json(args.ground_truth), read_json(args.raw_ground_truth), read_json(args.policy)
        plan = build_plan(corpus, policy, mode=args.mode, raw_corpus=raw, seed=args.seed, ground_truth_sha256=file_sha256(args.ground_truth), scoring_policy_sha256=file_sha256(args.policy), model=args.model, reasoning=args.reasoning, timeout_seconds=args.timeout_seconds, tool_call_limit=args.tool_call_limit)
        write_json(args.output, plan)
        print(json.dumps({"output": str(args.output), "mode": args.mode, "run_count": len(plan["schedule"]), "schedule_sha256": plan["schedule_sha256"]}, sort_keys=True))
        return 0
    if args.command == "validate-corpus":
        result = validate_phase08_corpus(read_json(args.ground_truth), args.mode, raw_corpus=read_json(args.raw_ground_truth) if args.raw_ground_truth else None)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "make-run-manifests":
        plan = read_json(args.plan)
        validate_schedule(plan.get("schedule", []), plan["mode"])
        args.output_dir.mkdir(parents=True, exist_ok=True)
        runtime_sha = read_json(args.bindings).get("artifactSha256", "") if args.bindings.is_file() else ""
        for entry in plan["schedule"]:
            catalog_path = args.catalog_dir / {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}[entry["condition"]]
            catalog_sha = read_json(catalog_path).get("artifactSha256", "") if catalog_path.is_file() else ""
            write_json(args.output_dir / f"{entry['run_id']}.json", build_manifest(plan, entry, transport=args.transport, catalog_sha256=catalog_sha, runtime_sha256=runtime_sha))
        print(json.dumps({"output_dir": str(args.output_dir), "run_count": len(plan["schedule"]), "plan_sha256": sha256_value(plan)}, sort_keys=True))
        return 0
    if args.command == "make-replacement-manifest":
        plan = read_json(args.plan)
        base = read_json(args.base_manifest)
        base_id = base.get("run_id")
        scheduled_id = base.get("replaces_run_id") or base_id
        entry = next((item for item in plan.get("schedule", []) if item.get("run_id") == scheduled_id), None)
        if not entry:
            raise SystemExit("base manifest is not a scheduled Phase 08 run")
        if any(item.get("run_id") == args.replacement_run_id for item in plan.get("schedule", [])):
            raise SystemExit("replacement run ID must be independent of scheduled run IDs")
        if args.replacement_run_id == base_id or not args.replacement_run_id.strip():
            raise SystemExit("replacement run ID must differ from the base run ID")
        replacement_manifest = build_manifest(
            plan,
            entry,
            transport=base.get("transport", "local-gateway"),
            catalog_sha256=base.get("catalog_sha256", ""),
            runtime_sha256=base.get("runtime_sha256", ""),
            replaces_run_id=scheduled_id,
        )
        replacement_manifest["run_id"] = args.replacement_run_id
        replacement_manifest["attempt"] = int(base.get("attempt", 1)) + 1
        write_json(args.output, replacement_manifest)
        print(json.dumps({"output": str(args.output), "run_id": args.replacement_run_id, "replaces_run_id": scheduled_id}, sort_keys=True))
        return 0
    if args.command == "integration-check":
        result = _integration(read_json(args.plan), args.frontend_root, args.catalog_dir, args.bindings, args.timeout_evidence)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["valid"] else 2
    if args.command == "verify-phase07-gate":
        result = validate_phase07_gate(args.root.resolve())
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["valid"] else 2
    if args.command == "verify-timeout-gate":
        evidence = read_json(args.evidence)
        validate_timeout_gate(evidence)
        if evidence.get("status") == "waived":
            print(json.dumps({"valid": True, "status": "waived", "reason": evidence["reason"]}, sort_keys=True))
        else:
            print(json.dumps({"valid": True, "timeout_seconds": 120, "turn_status": "interrupted"}, sort_keys=True))
        return 0
    if args.command == "summarize":
        result = aggregate_scores(read_json(args.plan), args.score_dir, args.manifest_dir, args.log_dir)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "serve":
        repository_root = Path(__file__).resolve().parents[2]
        if str(repository_root) not in sys.path:
            sys.path.insert(0, str(repository_root))
        from scripts.serve_phase07 import main as serve_main
        delegated = ["--run-manifest", str(args.run_manifest), "--host", args.host, "--port", str(args.port), "--frontend-root", str(args.frontend_root), "--catalog-dir", str(args.catalog_dir), "--bindings", str(args.bindings), "--env", str(args.env), "--log-dir", str(args.log_dir)]
        return serve_main(delegated)
    # Delegate lifecycle operations so Phase 08 has the same immutable log and
    # answer handling as Phase 07 without duplicating sensitive code.
    delegated = [args.command]
    for key, value in vars(args).items():
        if key == "command" or value is None or value is False:
            continue
        option = "--" + key.replace("_", "-")
        if value is True:
            delegated.append(option)
        else:
            delegated.extend([option, str(value)])
    return phase07_main(delegated)


if __name__ == "__main__":
    raise SystemExit(main())
