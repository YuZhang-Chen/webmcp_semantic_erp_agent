"""Build and verify the de-identified public Study 1 and Study 2 package.

The builder reads the local Phase 8 evidence tree, never contacts SAP, and
publishes only allowlisted projections. Original evidence remains under the
ignored private/build directories.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "research_artifacts"
PRIVATE = ROOT / "experiment" / "private" / "phase08"
STUDY1_BUILD = ROOT / "build" / "phase-08"
STUDY2_BUILD = ROOT / "build" / "phase-08-budget"
PHASE05 = ROOT / "build" / "phase-05"
PHASE06 = ROOT / "build" / "phase-06"
HEX_SHA256 = re.compile(r"\b[0-9a-fA-F]{64}\b")
LONG_DIGITS = re.compile(r"(?<!\d)\d{7,14}(?!\d)")
SENSITIVE_KEY_NAMES = {"task_id", "source_task_id", "candidate_id"}
BUSINESS_IDENTIFIER_KEYS = {"sales_order_id", "delivery_id", "billing_id", "billing_document_id", "customer_id", "sold_to_party_id"}
SAFE_ERROR_CATEGORIES = {"sap_query_error", "tool_budget_exhausted"}
SAFE_TERMINATIONS = {"agent_final_answer", "tool_call_limit_exceeded"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path.relative_to(ROOT)}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8", newline="\n")


def list_files(path: Path, pattern: str = "*") -> list[Path]:
    return sorted(p for p in path.glob(pattern) if p.is_file())


def nested_strings_with_ids(value: Any, key: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            found |= nested_strings_with_ids(child_value, str(child_key))
    elif isinstance(value, list):
        for child_value in value:
            found |= nested_strings_with_ids(child_value, key)
    elif isinstance(value, (str, int)) and key not in SENSITIVE_KEY_NAMES:
        if key in BUSINESS_IDENTIFIER_KEYS and value:
            found.add(str(value))
    return found


def event_projection(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not source_events:
        raise ValueError(f"Empty source log: {path.name}")
    run_ids = {event.get("run_id") for event in source_events}
    if len(run_ids) != 1:
        raise ValueError(f"A source log contains multiple run IDs: {path.name}")
    run_id = str(next(iter(run_ids)))
    projection: list[dict[str, Any]] = []
    for event in source_events:
        event_type = event.get("event_type")
        if event_type not in {"run_started", "tool_call", "run_completed", "run_invalid"}:
            raise ValueError(f"Unexpected event type in {path.name}: {event_type}")
        item: dict[str, Any] = {
            "schema_version": "public-event-projection-1.0",
            "run_id": run_id,
            "task_id": event.get("task_id"),
            "condition": event.get("condition"),
            "repetition": event.get("repetition"),
            "sequence": event.get("sequence"),
            "event_type": event_type,
        }
        if event_type == "run_started":
            context = event.get("run_context") or {}
            agent = context.get("agent") or {}
            item["agent"] = {
                key: agent[key]
                for key in ("model", "reasoning", "timeout_seconds", "tool_call_limit", "fresh_session_per_run")
                if key in agent
            }
            item["transport"] = context.get("transport")
            item["artifact_hashes"] = {
                key: context[key]
                for key in ("catalog_sha256", "runtime_sha256", "scoring_policy_sha256", "ground_truth_sha256")
                if isinstance(context.get(key), str)
            }
        elif event_type == "tool_call":
            for key in ("call_order", "canonical_operation", "tool_name", "duration_ms", "success", "executed"):
                if key in event:
                    item[key] = event[key]
            category = event.get("error_category")
            item["error_category"] = category if isinstance(category, str) and category in SAFE_ERROR_CATEGORIES else ("other" if category else None)
        elif event_type == "run_completed":
            reason = event.get("termination_reason")
            item["termination_reason"] = reason if reason in SAFE_TERMINATIONS else "other"
            item["answer_parse_status"] = "parsed" if not event.get("answer_parse_error") else "parse_error"
        elif event_type == "run_invalid":
            item["invalid"] = bool(event.get("invalid", True))
        projection.append(item)
    metadata = {
        "run_id": run_id,
        "event_count": len(projection),
        "event_types": {name: sum(row["event_type"] == name for row in projection) for name in sorted({row["event_type"] for row in projection})},
        "source_log_sha256": sha256_file(path),
        "projection_sha256": sha256_bytes("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in projection).encode("utf-8")),
    }
    return projection, metadata


def project_manifest(manifest: dict[str, Any], source_sha256: str, difficulty: str | None, budget: int | None, status: str) -> dict[str, Any]:
    agent = manifest.get("agent") or {}
    row: dict[str, Any] = {
        "run_id": manifest["run_id"],
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "repetition": manifest["repetition"],
        "schedule_index": manifest.get("schedule_index"),
        "mode": manifest.get("mode"),
        "transport": manifest.get("transport"),
        "attempt_status": status,
        "replacement_policy": manifest.get("replacement_policy"),
        "agent": {
            key: agent[key]
            for key in ("model", "reasoning", "timeout_seconds", "tool_call_limit", "fresh_session_per_run")
            if key in agent
        },
        "catalog_sha256": manifest.get("catalog_sha256"),
        "runtime_sha256": manifest.get("runtime_sha256"),
        "system_prompt_sha256": manifest.get("system_prompt_sha256"),
        "ground_truth_sha256": manifest.get("ground_truth_sha256"),
        "scoring_policy_sha256": manifest.get("scoring_policy_sha256"),
        "schedule_sha256": manifest.get("schedule_sha256"),
        "source_manifest_sha256": source_sha256,
    }
    if difficulty:
        row["difficulty"] = difficulty
    if budget is not None:
        row["tool_call_budget"] = budget
    if manifest.get("source_task_id"):
        row["source_task_id"] = manifest["source_task_id"]
    return row


def load_manifest_attempts(manifest_dir: Path, log_dir: Path, scores_by_id: dict[str, dict[str, Any]], difficulties: dict[str, str], budgets: dict[str, int] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    projected_manifests: list[dict[str, Any]] = []
    projected_events: list[dict[str, Any]] = []
    event_index: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for manifest_path in list_files(manifest_dir, "*.json"):
        manifest = read_json(manifest_path)
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str) or run_id in seen_run_ids:
            raise ValueError(f"Missing or duplicate run_id in manifest: {manifest_path.name}")
        if manifest_path.stem != run_id:
            raise ValueError(f"Manifest name does not match run_id: {manifest_path.name}")
        seen_run_ids.add(run_id)
        log_path = log_dir / f"{run_id}.jsonl"
        if not log_path.is_file():
            raise ValueError(f"Missing source log for {run_id}")
        events, metadata = event_projection(log_path)
        task_id = str(manifest["task_id"])
        if any(row["run_id"] != run_id or row["task_id"] != task_id for row in events):
            raise ValueError(f"Manifest/log identity mismatch: {run_id}")
        score = scores_by_id.get(run_id)
        if score and score.get("log_sha256") != metadata["source_log_sha256"]:
            raise ValueError(f"Score/log SHA-256 mismatch: {run_id}")
        if score and score.get("manifest_sha256") and score["manifest_sha256"] != sha256_file(manifest_path):
            raise ValueError(f"Score/manifest SHA-256 mismatch: {run_id}")
        event_types = {event["event_type"] for event in events}
        if score:
            status = "scored_replacement" if score.get("replacement") else "scored"
        elif "run_invalid" in event_types:
            status = "invalid_attempt"
        elif "run_completed" in event_types:
            raise ValueError(f"Completed attempt has no public score record: {run_id}")
        else:
            raise ValueError(f"Attempt is neither scored nor explicitly invalid: {run_id}")
        task_difficulty = difficulties.get(task_id)
        budget = budgets.get(task_id) if budgets else None
        projected_manifests.append(project_manifest(manifest, sha256_file(manifest_path), task_difficulty, budget, status))
        projected_events.extend(events)
        metadata["attempt_status"] = status
        metadata["source_manifest_sha256"] = sha256_file(manifest_path)
        event_index.append(metadata)
    projected_manifests.sort(key=lambda row: (row.get("schedule_index") or 0, row["run_id"]))
    projected_events.sort(key=lambda row: (row["run_id"], row.get("sequence") or 0))
    event_index.sort(key=lambda row: row["run_id"])
    return projected_manifests, projected_events, event_index


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text(path, "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    if not rows and not columns:
        raise ValueError(f"Cannot write an empty CSV without columns: {path}")
    fieldnames = columns or list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_schedule_json(path: Path, study: str, plan: dict[str, Any], attempts: list[dict[str, Any]], planned_slots: int, budget_mode: bool) -> None:
    difficulty_counts: dict[str, int] = defaultdict(int)
    difficulty_by_task = {row["task_id"]: row["difficulty"] for row in attempts if row.get("difficulty")}
    for difficulty in difficulty_by_task.values():
        difficulty_counts[difficulty] += 1
    planned_by_slot: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        slot = (row["task_id"], row["condition"], int(row["repetition"]))
        planned_by_slot[slot].append(row)
    selected_score_ids = {row["run_id"] for row in attempts if row["attempt_status"].startswith("scored")}
    schedule = {
        "schema_version": "public-schedule-projection-1.0",
        "study": study,
        "protocol": plan.get("protocol"),
        "source_id": plan.get("source_id"),
        "schema_version_source": plan.get("schema_version"),
        "schedule_sha256": plan.get("schedule_sha256"),
        "seed": plan.get("seed"),
        "planned_slot_count": planned_slots,
        "recorded_attempt_count": len(attempts),
        "conditions": ["A", "B", "C"],
        "agent": {
            key: (plan.get("agent") or {})[key]
            for key in ("model", "reasoning", "timeout_seconds", "fresh_session_per_run")
            if key in (plan.get("agent") or {})
        },
        "difficulty_task_counts": dict(sorted(difficulty_counts.items())) if difficulty_counts else {},
        "slot_attempts": [
            {
                "task_id": task_id,
                "condition": condition,
                "repetition": repetition,
                "attempt_ids": [row["run_id"] for row in slot_rows],
                "scored_run_id": next((row["run_id"] for row in slot_rows if row["run_id"] in selected_score_ids), None),
                "invalid_attempt_ids": [row["run_id"] for row in slot_rows if row["attempt_status"] == "invalid_attempt"],
                "replacement_used": any(row["attempt_status"] == "scored_replacement" for row in slot_rows),
            }
            for (task_id, condition, repetition), slot_rows in sorted(planned_by_slot.items())
        ],
        "attempts": attempts,
        "privacy_projection": {
            "task_prompt_text_included": False,
            "task_prompt_hashes_included": False,
            "ground_truth_values_included": False,
            "raw_answer_text_included": False,
        },
    }
    if budget_mode:
        schedule["budget_policy"] = "One call per required operation: D1=1, D2=2, D3=3."
        schedule["task_difficulty"] = plan.get("task_difficulty", {})
        schedule["task_budgets"] = plan.get("task_budgets", {})
    write_json(path, schedule)


def write_attempt_lineage(path: Path, attempts: list[dict[str, Any]], planned_slots: int, expected_scored: int) -> None:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in attempts:
        groups[(row["task_id"], row["condition"], int(row["repetition"]))].append(row)
    slots = []
    for (task_id, condition, repetition), rows in sorted(groups.items()):
        scored = [row for row in rows if row["attempt_status"].startswith("scored")]
        invalid = [row["run_id"] for row in rows if row["attempt_status"] == "invalid_attempt"]
        replacements = [row["run_id"] for row in scored if row["attempt_status"] == "scored_replacement"]
        slots.append({
            "task_id": task_id,
            "condition": condition,
            "repetition": repetition,
            "attempt_ids": [row["run_id"] for row in rows],
            "invalid_attempt_ids": invalid,
            "analyzed_run_id": scored[0]["run_id"] if scored else None,
            "replacement_used": bool(replacements),
            "replacement_run_id": replacements[0] if replacements else None,
        })
    invalid_attempt_count = sum(len(slot["invalid_attempt_ids"]) for slot in slots)
    scored_count = sum(slot["analyzed_run_id"] is not None for slot in slots)
    replacement_slots = sum(slot["replacement_used"] for slot in slots)
    if len(slots) != planned_slots or scored_count != expected_scored:
        raise ValueError(f"Slot accounting mismatch: slots={len(slots)}, scored={scored_count}")
    result = {
        "schema_version": "public-attempt-lineage-1.0",
        "planned_slots": planned_slots,
        "recorded_attempts": len(attempts),
        "invalid_attempts": invalid_attempt_count,
        "replacement_slots": replacement_slots,
        "scored_slots": scored_count,
        "missing_slots": sum(slot["analyzed_run_id"] is None for slot in slots),
        "slots": slots,
    }
    write_json(path, result)


def percentage(value: float) -> str:
    return f"{value * 100:.2f}%"


def write_study2_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Study 2 constrained-budget experiment report",
        "",
        "Study 2 is an independent supplementary study. It contains 12 coded tasks, three tool-description conditions, two repetitions per condition, and 72 valid runs. The per-task call budget equals the minimum required operations: D1=1, D2=2, and D3=3. Its denominator and tests are separate from Study 1.",
        "",
        f"Execution accounting: {summary['slot_accounting']['scored']} of {summary['planned_runs']} planned runs scored; {len(summary['slot_accounting']['invalid_slots'])} invalid slots, {len(summary['slot_accounting']['replacement_slots'])} replacement slots, and {len(summary['slot_accounting']['missing_score_slots'])} missing scores.",
        "",
        "## Results by condition",
        "",
        "| Condition | Runs | Success under budget | First choice | Minimal tool set | Budget exhaustion | Excess calls | Parameter accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition in ("A", "B", "C"):
        row = summary["by_condition"][condition]
        lines.append(
            f"| {condition} | {row['runs']} | {percentage(row['task_success_under_budget'])} | {percentage(row['first_choice_accuracy'])} | {percentage(row['minimal_tool_set_success'])} | {percentage(row['budget_exhaustion_rate'])} | {percentage(row['excess_call_rate'])} | {percentage(row['parameter_accuracy'])} |"
        )
    lines += [
        "",
        "## Results by task difficulty",
        "",
        "| Difficulty | Runs | Success under budget | First choice | Budget exhaustion | Minimal tool set | Parameter accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for difficulty in ("D1", "D2", "D3"):
        row = summary["by_difficulty"][difficulty]
        lines.append(
            f"| {difficulty} | {row['runs']} | {percentage(row['task_success_under_budget'])} | {percentage(row['first_choice_accuracy'])} | {percentage(row['budget_exhaustion_rate'])} | {percentage(row['minimal_tool_set_success'])} | {percentage(row['parameter_accuracy'])} |"
        )
    lines += [
        "",
        "## Paired comparisons",
        "",
        "The analysis pairs conditions by task and repetition. The six primary comparisons use two-sided exact McNemar tests with Holm correction. The values below are reported from the frozen Study 2 summary.",
        "",
        "| Pair | Metric | Difference (A-B, percentage points) | Discordant pairs | Exact p | Holm-adjusted p |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["paired_comparisons"]:
        discordant = row["mcnemar"]["discordant"]
        lines.append(
            f"| {row['a']}–{row['b']} | {row['metric']} | {row['absolute_percentage_point_difference']:+.2f} | {discordant} | {row['mcnemar']['p_value']:.5f} | {row['holm_adjusted_p_value']:.5f} |"
        )
    lines += [
        "",
        "The descriptive results show the largest difference in D2. The Holm-adjusted primary comparisons do not reach α=0.05; this study therefore does not establish a statistically significant advantage for any condition. D1 has a protocol-related floor effect and D3 is at ceiling, so the overall differences should be interpreted with the difficulty-specific results.",
        "",
        "## Scope of the public package",
        "",
        "The release includes run-level scores, a coded schedule, event projections, the frozen scoring policy, and hashes for integrity checks. It excludes Ground Truth values, exact task prompts, raw answers, and original execution logs. The public package supports recalculating aggregate statistics and auditing the projected event sequence, but it cannot independently rescore the private raw answers against SAP Ground Truth.",
    ]
    write_text(path, "\n".join(lines))


def private_evidence_manifest() -> dict[str, Any]:
    roots = {
        "phase08_private_artifacts": PRIVATE,
        "candidate_private_artifacts": ROOT / "experiment" / "private" / "candidate",
        "study1_build_evidence": STUDY1_BUILD,
        "study2_build_evidence": STUDY2_BUILD,
    }
    families: dict[str, Any] = {}
    all_files: list[dict[str, Any]] = []
    for name, directory in roots.items():
        family_files: list[dict[str, Any]] = []
        if directory.exists():
            for file_path in sorted(p for p in directory.rglob("*") if p.is_file()):
                if file_path.name == "release-v1.0.0-private-evidence-manifest.json":
                    continue
                entry = {"path": file_path.relative_to(ROOT).as_posix(), "bytes": file_path.stat().st_size, "sha256": sha256_file(file_path)}
                family_files.append(entry)
                all_files.append(entry)
        family_digest_material = "".join(f"{item['path']}\0{item['bytes']}\0{item['sha256']}\n" for item in family_files).encode("utf-8")
        families[name] = {
            "file_count": len(family_files),
            "total_bytes": sum(item["bytes"] for item in family_files),
            "commitment_sha256": sha256_bytes(family_digest_material),
            "files": family_files,
        }
    return {
        "schema_version": "private-evidence-manifest-1.0",
        "purpose": "Offline inventory for encrypted backup and later evidence-integrity checks. This file and all listed source files are private and must not be published.",
        "families": families,
        "total_file_count": len(all_files),
        "total_bytes": sum(item["bytes"] for item in all_files),
    }


def write_public_private_commitments(path: Path, manifest: dict[str, Any]) -> None:
    families = []
    for name, value in manifest["families"].items():
        families.append({
            "family": name,
            "file_count": value["file_count"],
            "total_bytes": value["total_bytes"],
            "commitment_sha256": value["commitment_sha256"],
        })
    write_json(path, {
        "schema_version": "private-evidence-commitments-1.0",
        "description": "Family-level commitments to the local private evidence inventory. No private filenames, paths, SAP values, raw-answer hashes, or evidence payloads are included.",
        "families": families,
    })


def write_hash_manifest(output: Path) -> None:
    entries = []
    for file_path in sorted(p for p in output.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"):
        entries.append(f"{sha256_file(file_path)}  {file_path.relative_to(output).as_posix()}")
    write_text(output / "MANIFEST.sha256", "\n".join(entries))


def extract_raw_answer_tokens() -> set[str]:
    paths: list[Path] = []
    for path in (PRIVATE / "answers", STUDY1_BUILD / "headless-runs", STUDY2_BUILD / "answers"):
        if path.exists():
            paths.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in {".txt", ".raw"})
    tokens: set[str] = set()
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        tokens.update(LONG_DIGITS.findall(content))
    return tokens


def audit_public_output(output: Path, raw_answer_tokens: set[str]) -> None:
    exact_ids: set[str] = set()
    for path in (PRIVATE / "formal-ground-truth-raw-human-confirmed-v1.json", PRIVATE / "budget-ground-truth-raw-v1.json"):
        if path.is_file():
            exact_ids |= nested_strings_with_ids(read_json(path))
    all_sensitive_values = exact_ids | raw_answer_tokens
    for file_path in (p for p in output.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        without_hashes = HEX_SHA256.sub("[sha256]", content)
        if any(value and value in without_hashes for value in all_sensitive_values):
            raise ValueError(f"Public output contains a value found in private SAP evidence: {file_path.relative_to(output)}")
        if re.search(r"(?i)(?:api[_ -]?key|password|secret|bearer)\s*[:=]\s*[^<\s][^\s|]{7,}", without_hashes):
            raise ValueError(f"Public output contains a credential-like assignment: {file_path.relative_to(output)}")
        if "-----BEGIN PRIVATE KEY-----" in without_hashes:
            raise ValueError(f"Public output contains a private-key marker: {file_path.relative_to(output)}")
    for file_path in output.rglob("*.jsonl"):
        for line in file_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            allowed = {
                "schema_version", "run_id", "task_id", "condition", "repetition", "sequence", "event_type",
                "agent", "transport", "artifact_hashes", "call_order", "canonical_operation", "tool_name",
                "duration_ms", "success", "executed", "error_category", "termination_reason", "answer_parse_status", "invalid",
            }
            if set(row) - allowed:
                raise ValueError(f"Unexpected event projection fields in {file_path.relative_to(output)}")
            if "parameters" in row or "reported_outcome" in row or "result_summary" in row or "raw_answer_file" in row:
                raise ValueError(f"Raw evidence field in event projection {file_path.relative_to(output)}")


def verify_package(output: Path, check_source_ids: bool = True) -> dict[str, int]:
    manifest_path = output / "MANIFEST.sha256"
    if not manifest_path.is_file():
        raise ValueError("MANIFEST.sha256 is missing")
    expected: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        expected[name] = digest
    actual_paths = {p.relative_to(output).as_posix(): p for p in output.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256"}
    if set(expected) != set(actual_paths):
        missing = set(expected) - set(actual_paths)
        unlisted = set(actual_paths) - set(expected)
        raise ValueError(f"Release manifest file set mismatch: missing={len(missing)}, unlisted={len(unlisted)}")
    for name, path in actual_paths.items():
        if sha256_file(path) != expected[name]:
            raise ValueError(f"Release manifest hash mismatch: {name}")
    s1 = read_json(output / "study1_180_run" / "summary.json")
    s2 = read_json(output / "study2_constrained_budget_72_run" / "summary.json")
    if s1.get("valid_runs") != 180 or len(s1.get("runs", [])) != 180:
        raise ValueError("Study 1 must contain exactly 180 scored runs")
    if s2.get("valid_runs") != 72 or len(s2.get("runs", [])) != 72:
        raise ValueError("Study 2 must contain exactly 72 scored runs")
    if len(list((output / "study1_180_run" / "scores").glob("*.json"))) != 180:
        raise ValueError("Study 1 score file count mismatch")
    if len(list((output / "study2_constrained_budget_72_run" / "scores").glob("*.json"))) != 72:
        raise ValueError("Study 2 score file count mismatch")
    s1_schedule = read_json(output / "study1_180_run" / "schedule.json")
    s2_schedule = read_json(output / "study2_constrained_budget_72_run" / "schedule.json")
    if len(s1_schedule.get("attempts", [])) != 182 or len(s2_schedule.get("attempts", [])) != 72:
        raise ValueError("Public schedule attempt count mismatch")
    if check_source_ids:
        audit_public_output(output, extract_raw_answer_tokens())
    return {"files": len(actual_paths), "study1_scores": 180, "study1_attempts": 182, "study2_scores": 72, "study2_attempts": 72}


def build_release(output: Path) -> dict[str, int]:
    plan1_path = PRIVATE / "formal-plan-six-priority-v1.json"
    manifest1_dir = PRIVATE / "formal-run-manifests-six-priority-v1"
    score1_dir = PRIVATE / "scores"
    summary1_path = PRIVATE / "formal-summary-v1.json"
    plan2_path = PRIVATE / "budget-plan-v1.json"
    manifest2_dir = STUDY2_BUILD / "manifests"
    summary2_path = STUDY2_BUILD / "summary.json"
    for required in (plan1_path, manifest1_dir, score1_dir, summary1_path, plan2_path, manifest2_dir, summary2_path, PHASE05, PHASE06):
        if not required.exists():
            raise FileNotFoundError(f"Required study artifact is missing: {required.relative_to(ROOT)}")

    plan1 = read_json(plan1_path)
    plan2 = read_json(plan2_path)
    summary1 = read_json(summary1_path)
    summary2 = read_json(summary2_path)
    gt1 = read_json(PRIVATE / "formal-ground-truth-raw-human-confirmed-v1.json")
    difficulties1 = {case["task_id"]: case["difficulty"] for case in gt1["cases"]}
    difficulties2 = plan2.get("task_difficulty", {})
    budgets2 = plan2.get("task_budgets", {})
    score1_by_id = {row["run_id"]: row for row in summary1["runs"]}
    score2_by_id = {row["run_id"]: row for row in summary2["runs"]}
    if len(score1_by_id) != 180 or len(score2_by_id) != 72:
        raise ValueError("Expected 180 Study 1 and 72 Study 2 score rows")

    output.mkdir(parents=True, exist_ok=True)
    s1 = output / "study1_180_run"
    s2 = output / "study2_constrained_budget_72_run"
    shared = output / "shared_runtime"
    provenance = output / "provenance"
    for directory in (s1 / "scores", s1 / "events", s2 / "scores", s2 / "events", shared / "catalogs", provenance):
        directory.mkdir(parents=True, exist_ok=True)

    attempts1, events1, index1 = load_manifest_attempts(manifest1_dir, STUDY1_BUILD / "headless-runs", score1_by_id, difficulties1)
    attempts2, events2, index2 = load_manifest_attempts(manifest2_dir, STUDY2_BUILD / "logs", score2_by_id, difficulties2, budgets2)
    write_schedule_json(s1 / "schedule.json", "study1_formal", plan1, attempts1, 180, False)
    write_schedule_json(s2 / "schedule.json", "study2_constrained_budget", plan2, attempts2, 72, True)
    write_attempt_lineage(s1 / "attempt-lineage.json", attempts1, 180, 180)
    write_attempt_lineage(s2 / "attempt-lineage.json", attempts2, 72, 72)

    write_jsonl(s1 / "events" / "all-attempts.jsonl", events1)
    write_jsonl(s2 / "events" / "all-attempts.jsonl", events2)
    write_csv(s1 / "events" / "index.csv", index1)
    write_csv(s2 / "events" / "index.csv", index2)
    for run_id, row in score1_by_id.items():
        write_json(s1 / "scores" / f"{run_id}.json", row)
    for run_id, row in score2_by_id.items():
        write_json(s2 / "scores" / f"{run_id}.json", row)
    write_json(s1 / "summary.json", summary1)
    write_json(s2 / "summary.json", summary2)
    (s1 / "runs.csv").write_bytes((PRIVATE / "formal-runs-v1.csv").read_bytes())

    report1 = (PRIVATE / "formal-report-v1.md").read_text(encoding="utf-8")
    report1 = report1.replace("# Phase 08 正式 A/B/C 實驗完整報告", "# Study 1 正式 A/B/C 實驗報告")
    marker = "## 可重算 artifacts"
    if marker in report1:
        report1 = report1.split(marker, 1)[0].rstrip() + "\n\n## Public release artifacts\n\n"
    report1 += (
        "- Run-level CSV: `runs.csv`\n"
        "- Canonical run-level summary: `summary.json`\n"
        "- Individual scores: `scores/*.json`\n"
        "- Coded schedule and attempt lineage: `schedule.json`, `attempt-lineage.json`\n"
        "- Event projections: `events/all-attempts.jsonl` and `events/index.csv`\n\n"
        "The original manifests, execution logs, Ground Truth and raw answers remain private."
    )
    write_text(s1 / "report.md", report1)
    write_study2_report(s2 / "report.md", summary2)

    protocol = read_json(ROOT / "experiment" / "phase08-protocol.json")
    formal = protocol["formal"]
    agent = protocol["agent"]
    write_json(shared / "study1-formal-protocol.json", {
        "schema_version": "public-study-protocol-1.0",
        "study": "Study 1",
        "protocol": protocol["protocol"],
        "source_id": protocol["source_id"],
        "schedule_seed": protocol["seed"],
        "conditions": protocol["conditions"],
        "task_count": formal["task_count"],
        "repetitions_per_condition": formal["repetitions"],
        "planned_runs": formal["run_count"],
        "difficulty_quota": formal["difficulty_quota"],
        "agent": {key: agent[key] for key in ("model", "reasoning", "timeout_seconds", "tool_call_limit", "fresh_session_per_run")},
        "review_protocol": protocol["review_protocol"],
        "timeout_gate_status": protocol["timeout_gate"]["status"],
        "timeout_gate_note": "The researcher waived controlled timeout-interruption evidence on 2026-09-16; runtime timeout enforcement is not claimed as validated.",
    })
    write_json(shared / "study1-scoring-policy.json", read_json(ROOT / "experiment" / "scoring-policy.json"))
    write_json(shared / "study2-scoring-policy.json", read_json(ROOT / "experiment" / "phase08-budget-scoring-policy.json"))
    for filename in ("a-technical-tools.json", "b-typed-tools.json", "c-semantic-tools.json", "conditions-manifest.json"):
        source = PHASE05 / filename
        (shared / "catalogs" / filename).write_bytes(source.read_bytes())
    (shared / "runtime-bindings.json").write_bytes((PHASE06 / "runtime-bindings.json").read_bytes())

    private_manifest = private_evidence_manifest()
    write_json(ROOT / "experiment" / "private" / "release-v1.0.0-private-evidence-manifest.json", private_manifest)
    write_public_private_commitments(provenance / "private-evidence-commitments.json", private_manifest)
    write_json(provenance / "execution-code-provenance.json", {
        "schema_version": "execution-code-provenance-1.0",
        "study_runs_executed_from_dirty_working_tree": True,
        "runtime_changes_recorded_post_hoc_in_commit": "a5d917229d93043a36c8feb306ddcc97d3814575",
        "commit_is_a_byte_for_byte_snapshot_of_each_run": False,
        "changes": [
            {
                "path": "frontend/src/runtime/experiment.ts",
                "summary": "Treat the append-only logger's duplicate run_started HTTP 409 as success during browser reload bootstrap.",
            },
            {
                "path": "scripts/serve_phase07.py",
                "summary": "Accept the Phase 08 manifest schema and an injected argument list used by the constrained-budget workbench.",
            },
        ],
        "limitation": "The commit records both changes after the study runs; no per-run source-tree snapshot was retained.",
    })
    raw_answer_tokens = extract_raw_answer_tokens()
    audit_public_output(output, raw_answer_tokens)
    write_hash_manifest(output)
    return verify_package(output, check_source_ids=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--skip-private-id-scan", action="store_true", help="Use only for a release copy that does not have the private evidence tree available.")
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    try:
        if args.verify_only:
            result = verify_package(output, check_source_ids=not args.skip_private_id_scan)
        else:
            result = build_release(output)
        print("Public research release verified:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        if not args.verify_only:
            print(f"  private_evidence_manifest: {ROOT / 'experiment' / 'private' / 'release-v1.0.0-private-evidence-manifest.json'}")
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
