"""Run the researcher-side Phase 07 pilot workflow, one fresh Desktop task at a time.

Usage: python scripts/run_phase07_pilot.py prepare|next|serve|finish|invalidate|status
The script never sends Ground Truth to the browser or Agent. A researcher opens
each fresh Codex task in ChatGPT Desktop after ``serve`` prints the fixed prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "src"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from experiment.cli import main as experiment_cli  # noqa: E402
from experiment.phase07 import file_sha256, load_jsonl, validate_ground_truth, validate_scoring_policy  # noqa: E402
from experiment.runner import SYSTEM_PROMPT, build_pilot_plan, build_run_manifest, build_task_prompts, integration_check, project_id_only_case  # noqa: E402
from experiment.phase07 import canonical_bytes  # noqa: E402
from scripts.serve_phase06 import CATALOG_NAMES, Handler, read_env  # noqa: E402
from scripts.serve_phase07 import build_phase07_state  # noqa: E402

PRIVATE = ROOT / "experiment" / "private"
GROUND_TRUTH = PRIVATE / "ground-truth-sealed.json"
RAW_CORPUS = PRIVATE / "ground-truth-raw.json"
POLICY = ROOT / "experiment" / "scoring-policy.json"
PLAN = PRIVATE / "pilot-plan.json"
MANIFESTS = PRIVATE / "run-manifests"
LOGS = ROOT / "build" / "phase-07" / "runs"
ARCHIVE = LOGS / "archive"
SCORES = PRIVATE / "scores"
FRONTEND = ROOT / "frontend" / "dist"
CATALOGS = ROOT / "build" / "phase-05"
BINDINGS = ROOT / "build" / "phase-06" / "runtime-bindings.json"
ENV = ROOT / ".env"
RUN_ID = re.compile(r"^(P0[1-5])-([ABC])-R([1-3])$")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def key_from_env() -> str:
    key = read_env(ENV).get("HMAC_KEY") or read_env(ENV).get("PHASE07_HMAC_KEY", "")
    if len(key.encode("utf-8")) < 32:
        raise ValueError("HMAC_KEY in .env must contain at least 32 bytes")
    return key


def with_hmac_key(callback):
    prior = os.environ.get("HMAC_KEY")
    os.environ["HMAC_KEY"] = key_from_env()
    try:
        return callback()
    finally:
        if prior is None:
            os.environ.pop("HMAC_KEY", None)
        else:
            os.environ["HMAC_KEY"] = prior


def catalog_hash(condition: str) -> str:
    name = CATALOG_NAMES[condition]
    return read_json(CATALOGS / name)["artifactSha256"]


def make_manifest(plan: dict, entry: dict, *, replaces: str | None = None) -> dict:
    manifest = build_run_manifest(
        plan, entry, catalog_sha256=catalog_hash(entry["condition"]),
        runtime_sha256=read_json(BINDINGS)["artifactSha256"],
    )
    if replaces:
        manifest["replaces_run_id"] = replaces
    manifest.setdefault("attempt", int(entry.get("attempt", 1)))
    return manifest


def verified_plan(*, allow_old_system_prompt: bool = False) -> dict:
    plan = read_json(PLAN)
    if plan.get("ground_truth_sha256") != file_sha256(GROUND_TRUTH):
        raise ValueError("sealed Ground Truth changed after pilot plan was frozen")
    if plan.get("scoring_policy_sha256") != file_sha256(POLICY):
        raise ValueError("scoring policy changed after pilot plan was frozen")
    if plan.get("raw_ground_truth_sha256") and plan["raw_ground_truth_sha256"] != file_sha256(RAW_CORPUS):
        raise ValueError("researcher-private raw corpus changed after pilot plan was frozen")
    if plan.get("tasks") != build_task_prompts(read_json(RAW_CORPUS)):
        raise ValueError("task prompts differ from the frozen raw source")
    if len(plan.get("schedule", [])) != 15:
        raise ValueError("pilot plan must contain exactly 15 runs")
    if not allow_old_system_prompt and "system_prompt" not in plan:
        raise ValueError("pilot plan has no fixed Agent instruction; run prepare first")
    if "system_prompt" in plan and plan["system_prompt"] != SYSTEM_PROMPT:
        raise ValueError("fixed Agent instruction changed after plan was frozen")
    if "system_prompt" in plan and plan.get("system_prompt_sha256") != hashlib.sha256(canonical_bytes(SYSTEM_PROMPT)).hexdigest():
        raise ValueError("fixed Agent instruction hash is invalid")
    return plan


def state(run_id: str) -> str:
    score = SCORES / f"{run_id}.json"
    log = LOGS / f"{run_id}.jsonl"
    if score.is_file():
        return "scored"
    if not log.is_file():
        return "ready"
    try:
        events = load_jsonl(log)
    except (ValueError, json.JSONDecodeError):
        return "log_invalid"
    if any(event["event_type"] == "run_invalid" for event in events):
        return "invalid"
    if any(event["event_type"] == "run_completed" for event in events):
        return "closed"
    return "running_or_incomplete"


def pending_run(plan: dict) -> str | None:
    for entry in plan["schedule"]:
        base_id = entry["run_id"]
        if state(base_id) == "scored":
            continue
        # Keep compatibility with replacement manifests created before the
        # same-ID rerun rule was adopted.
        if any((MANIFESTS / f"{base_id[:-1]}{attempt}.json").is_file() and state(f"{base_id[:-1]}{attempt}") == "scored" for attempt in (2, 3)):
            continue
        return base_id
    return None


def require_run(run_id: str, plan: dict) -> dict:
    match = RUN_ID.fullmatch(run_id)
    if not match or not any(item["task_id"] == match[1] and item["condition"] == match[2] for item in plan["schedule"]):
        raise ValueError("run ID is outside the fixed P01–P05 × A/B/C schedule")
    manifest = read_json(MANIFESTS / f"{run_id}.json")
    if manifest.get("ground_truth_sha256") != plan["ground_truth_sha256"] or manifest.get("scoring_policy_sha256") != plan["scoring_policy_sha256"]:
        raise ValueError("run manifest does not match the frozen pilot plan")
    task_id = manifest["task_id"]
    if manifest.get("task_prompt") != plan["tasks"][task_id]["text"] or manifest.get("task_prompt_sha256") != plan["tasks"][task_id]["sha256"]:
        raise ValueError("run manifest task prompt changed")
    if manifest.get("agent") != plan["agent"]:
        raise ValueError("run manifest Agent settings changed")
    if manifest.get("system_prompt_sha256") != plan["system_prompt_sha256"]:
        raise ValueError("run manifest Agent instruction changed")
    if manifest.get("catalog_sha256") != catalog_hash(manifest["condition"]) or manifest.get("runtime_sha256") != read_json(BINDINGS)["artifactSha256"]:
        raise ValueError("catalog or runtime artifact changed")
    return manifest


def prepare() -> None:
    corpus, raw, policy = read_json(GROUND_TRUTH), read_json(RAW_CORPUS), read_json(POLICY)
    validate_ground_truth(corpus)
    validate_scoring_policy(policy)
    key = key_from_env()
    for case in corpus["cases"]:
        raw_case = next((item for item in raw["cases"] if item["task_id"] == case["task_id"]), None)
        if not raw_case:
            raise ValueError("raw corpus lacks an approved task")
        project_id_only_case(raw_case, case, key)
    gate = integration_check({"agent": {"model": "gpt-5.6-sol", "reasoning": "medium", "timeout_seconds": 120, "tool_call_limit": 8}, "schedule": build_pilot_plan(corpus, policy, prompt_source=raw)["schedule"]}, frontend_root=FRONTEND, catalog_dir=CATALOGS, bindings=BINDINGS)
    if not gate["valid"]:
        raise ValueError("integration artifacts failed: " + "; ".join(gate["missing"]))
    if PLAN.is_file():
        plan = verified_plan(allow_old_system_prompt=True)
        if "raw_ground_truth_sha256" not in plan:
            if LOGS.is_dir() and any(LOGS.glob("*.jsonl")):
                raise ValueError("existing run logs prevent freezing the raw source hash")
            plan["raw_ground_truth_sha256"] = file_sha256(RAW_CORPUS)
            PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if "system_prompt" not in plan:
            if LOGS.is_dir() and any(LOGS.glob("*.jsonl")):
                raise ValueError("existing run logs prevent adding a system prompt to the frozen plan")
            plan["system_prompt"] = SYSTEM_PROMPT
            plan["system_prompt_sha256"] = hashlib.sha256(canonical_bytes(SYSTEM_PROMPT)).hexdigest()
            PLAN.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        plan = build_pilot_plan(corpus, policy, prompt_source=raw, ground_truth_sha256=file_sha256(GROUND_TRUTH), scoring_policy_sha256=file_sha256(POLICY))
        plan["raw_ground_truth_sha256"] = file_sha256(RAW_CORPUS)
        write_new_json(PLAN, plan)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    for entry in plan["schedule"]:
        path = MANIFESTS / f"{entry['run_id']}.json"
        if not path.exists():
            write_new_json(path, make_manifest(plan, entry))
        elif read_json(path).get("system_prompt_sha256") != plan["system_prompt_sha256"]:
            if (LOGS / f"{entry['run_id']}.jsonl").exists():
                raise ValueError("run manifest already has a log and cannot be refreshed")
            path.write_text(json.dumps(make_manifest(plan, entry), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        require_run(entry["run_id"], plan)
    print("準備完成：5 題 × A/B/C = 15 runs；三組各 4 個 Site Tools；Ground Truth 已固定。")
    print("下一步：uv run python scripts/run_phase07_pilot.py next")


def show_next(plan: dict) -> None:
    run_id = pending_run(plan)
    if run_id is None:
        print("無下一筆 ready run；請用 status 檢查 closed、invalid 或 replacement 狀態。")
        return
    manifest = require_run(run_id, plan)
    current = state(run_id)
    print(f"下一筆：{run_id}（{manifest['condition']} condition；schedule #{manifest['schedule_index']}）")
    print(f"狀態：{current}")
    if current == "running_or_incomplete":
        print(f"此 run 已有執行紀錄；請保存 Agent 最終回答後執行：uv run python scripts/run_phase07_pilot.py finish --run-id {run_id} --answer-file experiment/private/answers/{run_id}.txt")
    elif current == "closed":
        print("此 run 已關閉但尚未計分；請確認 raw answer 封存後執行 finish。")
    elif current == "invalid":
        print(f"此 run 已標記 invalid；重跑同一 run ID：uv run python scripts/run_phase07_pilot.py serve --run-id {run_id} --rerun")
    else:
        print(f"啟動：uv run python scripts/run_phase07_pilot.py serve --run-id {run_id}")


def serve(run_id: str, port: int, plan: dict, rerun: bool = False) -> None:
    manifest = require_run(run_id, plan)
    if run_id != pending_run(plan):
        raise ValueError("run does not match the next scheduled task")
    current = state(run_id)
    if current != "ready":
        if not rerun:
            raise ValueError("run log already exists; use --rerun to archive the previous attempt and start the same run ID again")
        if current == "scored":
            raise ValueError("a scored run cannot be rerun; use a new protocol repetition")
        old_log = LOGS / f"{run_id}.jsonl"
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        attempt = int(manifest.get("attempt", 1))
        if attempt >= 3:
            raise ValueError("two reruns have already been used for this run ID")
        archived_log = ARCHIVE / f"{run_id}.attempt-{attempt}.jsonl"
        while archived_log.exists():
            attempt += 1
            archived_log = ARCHIVE / f"{run_id}.attempt-{attempt}.jsonl"
        if old_log.exists():
            shutil.move(str(old_log), str(archived_log))
        old_raw = LOGS / f"{run_id}.answer.raw"
        if old_raw.exists():
            shutil.move(str(old_raw), str(ARCHIVE / f"{run_id}.attempt-{attempt}.answer.raw"))
        manifest["attempt"] = attempt + 1
        (MANIFESTS / f"{run_id}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    gate = integration_check(plan, frontend_root=FRONTEND, catalog_dir=CATALOGS, bindings=BINDINGS)
    if not gate["valid"]:
        raise ValueError("integration artifacts failed: " + "; ".join(gate["missing"]))
    namespace = argparse.Namespace(run_manifest=MANIFESTS / f"{run_id}.json", frontend_root=FRONTEND, catalog_dir=CATALOGS, bindings=BINDINGS, env=ENV, log_dir=LOGS)
    runtime = build_phase07_state(namespace)
    server = ThreadingHTTPServer(("localhost", port), Handler)
    server.runtime_state = runtime  # type: ignore[attr-defined]
    print(f"Workbench: http://localhost:{port}  |  {run_id}", flush=True)
    print("在 ChatGPT Desktop built-in browser 開啟上方網址，確認 WebMCP 註冊四個工具。", flush=True)
    print("每筆建立全新的 Codex task；模型與 reasoning 使用 manifest 固定設定。", flush=True)
    print("固定 system prompt：\n" + plan["system_prompt"], flush=True)
    print("固定 task prompt：\n" + manifest["task_prompt"], flush=True)
    print("完成後將 Agent 的最後回答原樣存入 experiment/private/answers/<run-id>.txt，關閉此 server，再執行 finish。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def finish(run_id: str, answer_file: Path, plan: dict) -> None:
    manifest = require_run(run_id, plan)
    if state(run_id) not in {"running_or_incomplete", "closed"}:
        raise ValueError("run has no active log or was marked invalid")
    if not answer_file.is_file():
        raise ValueError("raw final answer file is missing")
    log = LOGS / f"{run_id}.jsonl"
    if state(run_id) == "running_or_incomplete":
        with_hmac_key(lambda: experiment_cli(["close-run", "--log", str(log), "--answer-file", str(answer_file)]))
    SCORES.mkdir(parents=True, exist_ok=True)
    with_hmac_key(lambda: experiment_cli(["score-run", "--log", str(log), "--ground-truth", str(GROUND_TRUTH), "--raw-ground-truth", str(RAW_CORPUS), "--policy", str(POLICY), "--task-id", manifest["task_id"], "--output", str(SCORES / f"{run_id}.json")]))
    print("已保存 raw answer、完成 JSONL 並計分。下一步：uv run python scripts/run_phase07_pilot.py next")


def invalidate(run_id: str, kind: str, operator: str, note: str, plan: dict) -> None:
    manifest = require_run(run_id, plan)
    if state(run_id) != "running_or_incomplete":
        raise ValueError("only an incomplete, unscored run can be marked invalid")
    with_hmac_key(lambda: experiment_cli(["record-intervention", "--log", str(LOGS / f"{run_id}.jsonl"), "--type", kind, "--operator", operator, "--note", note, "--invalid", "--replacement-run-id", run_id]))
    print(f"原 run {run_id} 已保留並標記 invalid；下一次使用同一 ID 加 --rerun。")


def status(plan: dict) -> None:
    for entry in plan["schedule"]:
        run_id = entry["run_id"]
        manifest = read_json(MANIFESTS / f"{run_id}.json")
        archive_count = len(list(ARCHIVE.glob(f"{run_id}.attempt-*.jsonl"))) if ARCHIVE.is_dir() else 0
        print(f"{run_id}:attempt-{manifest.get('attempt', 1)}:{state(run_id)}:archived-{archive_count}")
    print("下一筆：" + str(pending_run(plan)))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Phase 07 Desktop pilot workflow")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare")
    commands.add_parser("next")
    commands.add_parser("status")
    serving = commands.add_parser("serve")
    serving.add_argument("--run-id", required=True)
    serving.add_argument("--port", type=int, default=5173)
    serving.add_argument("--rerun", action="store_true", help="archive the previous incomplete/invalid attempt and reuse the same run ID")
    completed = commands.add_parser("finish")
    completed.add_argument("--run-id", required=True)
    completed.add_argument("--answer-file", type=Path, required=True)
    invalid = commands.add_parser("invalidate")
    invalid.add_argument("--run-id", required=True)
    invalid.add_argument("--type", choices=["environment_repair", "decision_guidance"], required=True)
    invalid.add_argument("--operator", required=True)
    invalid.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare()
            return 0
        plan = verified_plan()
        if args.command == "next":
            show_next(plan)
        elif args.command == "serve":
            serve(args.run_id, args.port, plan, args.rerun)
        elif args.command == "finish":
            finish(args.run_id, args.answer_file.resolve(), plan)
        elif args.command == "invalidate":
            invalidate(args.run_id, args.type, args.operator, args.note, plan)
        else:
            status(plan)
        return 0
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError, OSError) as exc:
        parser.exit(2, f"pilot workflow error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
