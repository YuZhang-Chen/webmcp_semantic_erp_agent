"""CLI for Phase 07 corpus validation, review packets, logs, and scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .candidates import CandidateScanner, build_gateway_from_env
from .phase07 import canonical_bytes, file_sha256, load_jsonl, pseudonymize, score_run, utc_now, validate_ground_truth, validate_scoring_policy
from .runner import build_pilot_plan, build_run_manifest, integration_check, parse_reported_outcome, project_id_only_case, validate_reported_outcome


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="phase07-experiment")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-corpus")
    validate.add_argument("--ground-truth", type=Path, required=True)
    validate.add_argument("--policy", type=Path, required=True)
    validate.add_argument("--allow-draft", action="store_true")
    seal = commands.add_parser("seal-corpus")
    seal.add_argument("--ground-truth", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--hmac-key-env", default="HMAC_KEY")
    confirm = commands.add_parser("confirm-ground-truth")
    confirm.add_argument("--ground-truth", type=Path, required=True)
    confirm.add_argument("--task-id", required=True)
    confirm.add_argument("--researcher", required=True)
    confirm.add_argument("--output", type=Path, required=True)
    review = commands.add_parser("export-review")
    review.add_argument("--ground-truth", type=Path, required=True)
    review.add_argument("--task-id", required=True)
    review.add_argument("--output", type=Path, required=True)
    review.add_argument("--hmac-key-env", default="HMAC_KEY")
    imported = commands.add_parser("import-review")
    imported.add_argument("--ground-truth", type=Path, required=True)
    imported.add_argument("--packet", type=Path, required=True)
    imported.add_argument("--review", type=Path, required=True)
    imported.add_argument("--output", type=Path, required=True)
    approve = commands.add_parser("approve-ground-truth")
    approve.add_argument("--ground-truth", type=Path, required=True)
    approve.add_argument("--task-id", required=True)
    approve.add_argument("--output", type=Path, required=True)
    approve.add_argument("--resolution-note")
    score = commands.add_parser("score-run")
    score.add_argument("--log", type=Path, required=True)
    score.add_argument("--ground-truth", type=Path, required=True)
    score.add_argument("--raw-ground-truth", type=Path, help="researcher-private raw corpus verified against the sealed corpus for ID-only scoring")
    score.add_argument("--policy", type=Path, required=True)
    score.add_argument("--reported-outcome", type=Path)
    score.add_argument("--task-id", required=True)
    score.add_argument("--output", type=Path)
    score.add_argument("--hmac-key-env", default="HMAC_KEY")
    verify = commands.add_parser("verify-log")
    verify.add_argument("--log", type=Path, required=True)
    close = commands.add_parser("close-run")
    close.add_argument("--log", type=Path, required=True)
    close.add_argument("--answer-file", type=Path, required=True)
    close.add_argument("--reported-outcome", type=Path)
    close.add_argument("--hmac-key-env", default="HMAC_KEY")
    scan = commands.add_parser("scan-candidates", help="scan live SAP OData for Phase 07 pilot candidates")
    scan.add_argument("--env", type=Path, default=Path(".env"))
    scan.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    scan.add_argument("--output", type=Path, required=True)
    scan.add_argument("--date-from")
    scan.add_argument("--date-to")
    scan.add_argument("--customer-id")
    scan.add_argument("--order-status", choices=["not_started", "partially_completed", "completed"])
    scan.add_argument("--limit", type=int, default=30)
    scan.add_argument("--delay-ms", type=int, default=100)
    scan.add_argument("--fail-fast", action="store_true")
    prepare = commands.add_parser("prepare-pilot", help="freeze prompts and create the reproducible 15-run pilot plan")
    prepare.add_argument("--ground-truth", type=Path, required=True)
    prepare.add_argument("--prompt-source", type=Path, help="researcher-private raw corpus used only to construct task prompts")
    prepare.add_argument("--policy", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--model", default="gpt-5.6-sol")
    prepare.add_argument("--reasoning", default="medium")
    prepare.add_argument("--timeout-seconds", type=int, default=120)
    prepare.add_argument("--tool-call-limit", type=int, default=8)
    manifest = commands.add_parser("make-run-manifests", help="materialize one manifest per scheduled run")
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--output-dir", type=Path, required=True)
    manifest.add_argument("--transport", choices=["direct-browser", "local-gateway"], default="local-gateway")
    manifest.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    manifest.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    check = commands.add_parser("integration-check", help="check artifacts before the browser integration gate")
    check.add_argument("--plan", type=Path, required=True)
    check.add_argument("--frontend-root", type=Path, default=Path("frontend/dist"))
    check.add_argument("--catalog-dir", type=Path, default=Path("build/phase-05"))
    check.add_argument("--bindings", type=Path, default=Path("build/phase-06/runtime-bindings.json"))
    check.add_argument("--output", type=Path)
    intervention = commands.add_parser("record-intervention", help="append a human intervention event to a run")
    intervention.add_argument("--log", type=Path, required=True)
    intervention.add_argument("--type", required=True, choices=["authentication", "authorization", "start", "environment_repair", "decision_guidance"])
    intervention.add_argument("--operator", required=True)
    intervention.add_argument("--invalid", action="store_true")
    intervention.add_argument("--note", default="")
    intervention.add_argument("--replacement-run-id")
    intervention.add_argument("--hmac-key-env", default="HMAC_KEY")
    intervention.add_argument("--output", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "prepare-pilot":
        ground_truth, policy = read_json(args.ground_truth), read_json(args.policy)
        validate_ground_truth(ground_truth)
        validate_scoring_policy(policy)
        prompt_source = read_json(args.prompt_source) if args.prompt_source else ground_truth
        plan = build_pilot_plan(ground_truth, policy, prompt_source=prompt_source, ground_truth_sha256=file_sha256(args.ground_truth), scoring_policy_sha256=file_sha256(args.policy), model=args.model, reasoning=args.reasoning, timeout_seconds=args.timeout_seconds, tool_call_limit=args.tool_call_limit)
        write_json(args.output, plan)
        print(json.dumps({"output": str(args.output), "run_count": len(plan["schedule"]), "ground_truth_sha256": plan["ground_truth_sha256"]}, sort_keys=True))
        return 0
    if args.command == "make-run-manifests":
        plan = read_json(args.plan)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        bindings_artifact = read_json(args.bindings).get("artifactSha256", "") if args.bindings.is_file() else ""
        for entry in plan.get("schedule", []):
            catalog_path = args.catalog_dir / {"A": "a-technical-tools.json", "B": "b-typed-tools.json", "C": "c-semantic-tools.json"}[entry["condition"]]
            catalog_artifact = read_json(catalog_path).get("artifactSha256", "") if catalog_path.is_file() else ""
            manifest = build_run_manifest(plan, entry, transport=args.transport, catalog_sha256=catalog_artifact, runtime_sha256=bindings_artifact)
            write_json(args.output_dir / f"{entry['run_id']}.json", manifest)
        print(json.dumps({"output_dir": str(args.output_dir), "run_count": len(plan.get("schedule", []))}, sort_keys=True))
        return 0
    if args.command == "integration-check":
        plan = read_json(args.plan)
        result = integration_check(plan, frontend_root=args.frontend_root, catalog_dir=args.catalog_dir, bindings=args.bindings)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["valid"] else 2
    if args.command == "scan-candidates":
        private_root = (Path("experiment") / "private").resolve()
        output_path = args.output.resolve()
        if private_root not in output_path.parents:
            raise SystemExit("raw candidate evidence must be written under experiment/private/")
        artifact = read_json(args.bindings)
        criteria = {
            key: value for key, value in {
                "date_from": args.date_from,
                "date_to": args.date_to,
                "customer_id": args.customer_id,
                "order_status": args.order_status,
            }.items() if value
        }
        canonical_criteria = {
            ("order_date_from" if key == "date_from" else "order_date_to" if key == "date_to" else key): value
            for key, value in criteria.items()
        }
        if not canonical_criteria:
            raise SystemExit("at least one of --date-from, --date-to, --customer-id, --order-status is required")
        scanner = CandidateScanner(artifact, build_gateway_from_env(args.env, artifact), delay_ms=args.delay_ms)
        result = scanner.scan(canonical_criteria, limit=args.limit, fail_fast=args.fail_fast)
        write_json(args.output, result)
        print(json.dumps({
            "classification": result["classification"],
            "candidate_count": len(result["candidates"]),
            "failure_count": len(result["failures"]),
            "suggested_assignments": result["suggested_assignments"],
            "output": str(args.output),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "validate-corpus":
        ground_truth, policy = read_json(args.ground_truth), read_json(args.policy)
        validate_ground_truth(ground_truth, require_approved=not args.allow_draft)
        validate_scoring_policy(policy)
        print(json.dumps({"case_count": len(ground_truth["cases"]), "valid": True}, sort_keys=True))
        return 0
    if args.command == "seal-corpus":
        ground_truth = read_json(args.ground_truth)
        validate_ground_truth(ground_truth, require_approved=False)
        secret = os.environ.get(args.hmac_key_env, "")
        if len(secret.encode("utf-8")) < 32:
            raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
        sealed = pseudonymize(ground_truth, secret.encode("utf-8"))
        sealed["sealed_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        write_json(args.output, sealed)
        print(json.dumps({"output": str(args.output), "case_count": len(sealed["cases"])}, sort_keys=True))
        return 0
    if args.command == "confirm-ground-truth":
        ground_truth = read_json(args.ground_truth)
        validate_ground_truth(ground_truth, require_approved=False)
        case = next((item for item in ground_truth["cases"] if item["task_id"] == args.task_id), None)
        if not case:
            raise SystemExit(f"unknown task_id: {args.task_id}")
        case.setdefault("review", {})["human_confirmation"] = {
            "researcher": args.researcher,
            "confirmed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source_id": "webmcp.sap_sd.odata",
        }
        case["status"] = "human_confirmed"
        write_json(args.output, ground_truth)
        return 0
    if args.command == "export-review":
        ground_truth = read_json(args.ground_truth)
        validate_ground_truth(ground_truth, require_approved=False)
        case = next((item for item in ground_truth["cases"] if item["task_id"] == args.task_id), None)
        if not case:
            raise SystemExit(f"unknown task_id: {args.task_id}")
        secret = os.environ.get(args.hmac_key_env, "")
        if len(secret.encode("utf-8")) < 32:
            raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
        packet = {"schema_version": "1.0", "task_id": args.task_id, "evidence": pseudonymize(case, secret.encode("utf-8"))}
        packet["packet_sha256"] = hashlib.sha256(canonical_bytes(packet)).hexdigest()
        write_json(args.output, packet)
        print(json.dumps({"output": str(args.output), "packet_sha256": packet["packet_sha256"]}, sort_keys=True))
        return 0
    if args.command == "import-review":
        ground_truth, packet, review = read_json(args.ground_truth), read_json(args.packet), read_json(args.review)
        unsigned_packet = {key: value for key, value in packet.items() if key != "packet_sha256"}
        expected_hash = hashlib.sha256(canonical_bytes(unsigned_packet)).hexdigest()
        if packet.get("packet_sha256") != expected_hash or review.get("packet_sha256") != expected_hash:
            raise SystemExit("review packet hash mismatch")
        if review.get("task_id") != packet.get("task_id") or review.get("verdict") not in {"agree", "disagree"} or not review.get("model"):
            raise SystemExit("invalid LLM review response")
        case = next((item for item in ground_truth["cases"] if item["task_id"] == review["task_id"]), None)
        if not case or not case.get("review", {}).get("human_confirmation"):
            raise SystemExit("human confirmation is required before LLM review")
        case.setdefault("review", {})["llm_review"] = {
            "model": review["model"],
            "verdict": review["verdict"],
            "issues": review.get("issues", []),
            "reviewed_at": review.get("reviewed_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "packet_sha256": expected_hash,
        }
        case["status"] = "llm_reviewed"
        write_json(args.output, ground_truth)
        return 0
    if args.command == "approve-ground-truth":
        ground_truth = read_json(args.ground_truth)
        case = next((item for item in ground_truth["cases"] if item["task_id"] == args.task_id), None)
        confirmation = (case or {}).get("review", {}).get("human_confirmation")
        if not case or not confirmation:
            raise SystemExit("human confirmation is required")
        if ground_truth.get("review_protocol", "human_plus_llm") == "human_only":
            case["review"]["human_approval"] = {
                "researcher": confirmation["researcher"],
                "approved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "protocol": "human_only",
            }
        else:
            llm = case.get("review", {}).get("llm_review")
            if not llm:
                raise SystemExit("LLM review is required by human_plus_llm protocol")
            if llm["verdict"] == "disagree":
                if not args.resolution_note:
                    raise SystemExit("researcher resolution is required for an LLM disagreement")
                case["review"]["researcher_resolution"] = {
                    "note": args.resolution_note,
                    "resolved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
        case["status"] = "approved"
        validate_ground_truth({
            "schema_version": ground_truth["schema_version"],
            "corpus_id": ground_truth["corpus_id"],
            "review_protocol": ground_truth.get("review_protocol", "human_plus_llm"),
            "cases": [case],
        })
        write_json(args.output, ground_truth)
        return 0
    if args.command == "verify-log":
        events = load_jsonl(args.log)
        completed = next((event for event in events if event["event_type"] == "run_completed"), None)
        if completed and completed.get("raw_answer_file"):
            raw_path = args.log.with_name(completed["raw_answer_file"])
            if not raw_path.is_file() or file_sha256(raw_path) != completed["answer_sha256"]:
                raise SystemExit("archived raw final answer is missing or changed")
        print(json.dumps({"event_count": len(events), "file_sha256": file_sha256(args.log), "valid": True}, sort_keys=True))
        return 0
    if args.command == "record-intervention":
        events = load_jsonl(args.log)
        if any(event["event_type"] == "run_completed" for event in events):
            raise SystemExit("run is already completed")
        if args.invalid and sum(event.get("event_type") == "run_invalid" for event in events) >= 2:
            raise SystemExit("replacement limit (2) has been reached for this run")
        first = events[0]
        key = os.environ.get(args.hmac_key_env, "")
        if len(key.encode("utf-8")) < 32:
            raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
        event = {
            "schema_version": "1.0", "run_id": first["run_id"], "task_id": first["task_id"], "condition": first["condition"], "repetition": first["repetition"],
            "sequence": len(events) + 1, "timestamp": utc_now(), "event_type": "run_invalid" if args.invalid else "intervention", "actor": "researcher",
            "intervention_type": args.type, "operator": args.operator, "invalid": bool(args.invalid), "reason": args.note or args.type, "note": args.note,
            "replacement_run_id": args.replacement_run_id,
        }
        stored = pseudonymize(event, key.encode("utf-8"))
        with args.log.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_bytes(stored).decode("utf-8") + "\n")
        if args.output:
            write_json(args.output, stored)
        print(json.dumps({"run_id": first["run_id"], "event_type": event["event_type"], "invalid": event["invalid"]}, sort_keys=True))
        return 0
    if args.command == "close-run":
        events = load_jsonl(args.log)
        if any(event["event_type"] == "run_completed" for event in events):
            raise SystemExit("run is already completed")
        secret = os.environ.get(args.hmac_key_env, "")
        if len(secret.encode("utf-8")) < 32:
            raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
        answer = args.answer_file.read_bytes()
        first = events[0]
        raw_copy = args.log.with_name(f"{args.log.stem}.answer.raw")
        if raw_copy.exists():
            raise SystemExit(f"raw answer archive already exists: {raw_copy}")
        raw_copy.write_bytes(answer)
        try:
            reported = parse_reported_outcome(args.answer_file)
            parse_error = None
        except ValueError as exc:
            reported = {"sales_orders": [], "deliveries": [], "billings": []}
            parse_error = str(exc)
        completed = {
            "schema_version": "1.0",
            **{field: first[field] for field in ("run_id", "task_id", "condition", "repetition")},
            "sequence": len(events) + 1,
            "timestamp": utc_now(),
            "received_at": utc_now(),
            "event_type": "run_completed",
            "actor": "researcher",
            "answer_sha256": hashlib.sha256(answer).hexdigest(),
            "answer_bytes": len(answer),
            "raw_answer_file": raw_copy.name,
            "reported_outcome": pseudonymize(reported, secret.encode("utf-8")),
            "answer_parse_error": parse_error,
        }
        if args.reported_outcome:
            try:
                supplied = validate_reported_outcome(read_json(args.reported_outcome))
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            if supplied != reported:
                raise SystemExit("reported outcome does not match the raw final answer; researcher rewriting is not allowed")
        with args.log.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_bytes(completed).decode("utf-8") + "\n")
        print(json.dumps({"file_sha256": file_sha256(args.log), "run_id": first["run_id"]}, sort_keys=True))
        return 0
    ground_truth, policy = read_json(args.ground_truth), read_json(args.policy)
    validate_ground_truth(ground_truth)
    case = next((item for item in ground_truth["cases"] if item["task_id"] == args.task_id), None)
    if not case:
        raise SystemExit(f"unknown task_id: {args.task_id}")
    secret = os.environ.get(args.hmac_key_env, "")
    if len(secret.encode("utf-8")) < 32:
        raise SystemExit(f"{args.hmac_key_env} must contain at least 32 bytes")
    if args.raw_ground_truth:
        raw_document = read_json(args.raw_ground_truth)
        raw_case = next((item for item in raw_document.get("cases", []) if item.get("task_id") == args.task_id), None)
        if not raw_case:
            raise SystemExit("raw corpus lacks the selected task")
        case = project_id_only_case(raw_case, case, secret)
    events = load_jsonl(args.log)
    completed_event = next((event for event in reversed(events) if event["event_type"] == "run_completed"), None)
    if not completed_event:
        raise SystemExit("execution log is incomplete; run_completed is required before scoring")
    if completed_event.get("raw_answer_file"):
        raw_path = args.log.with_name(completed_event["raw_answer_file"])
        if not raw_path.is_file() or file_sha256(raw_path) != completed_event["answer_sha256"]:
            raise SystemExit("archived raw final answer is missing or changed")
    if args.reported_outcome:
        try:
            reported_raw = validate_reported_outcome(read_json(args.reported_outcome))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        reported = pseudonymize(reported_raw, secret.encode("utf-8"))
        if reported != completed_event["reported_outcome"]:
            raise SystemExit("reported outcome differs from archived raw final answer")
    else:
        reported = completed_event["reported_outcome"]
    invalid_event = next((event for event in events if event["event_type"] == "run_invalid" and event.get("invalid") is True), None)
    if invalid_event:
        raise SystemExit("run is invalid and cannot be scored; use its replacement run")
    result = score_run(events, case, policy, reported)
    if completed_event.get("answer_parse_error"):
        result["task_success"] = 0
        result["error_categories"] = sorted(set(result["error_categories"]) | {"answer_synthesis_error"})
    result["log_sha256"] = file_sha256(args.log)
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
