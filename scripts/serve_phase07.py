"""Serve the Phase 07 workbench with local append-only execution logging."""

from __future__ import annotations

import argparse
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

# When invoked as ``python scripts/serve_phase07.py``, Python places only the
# scripts directory on sys.path. Add the repository root so the sibling
# module import below works both as a script and as an imported test module.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from experiment.phase07 import ExperimentLogWriter
from scripts.serve_phase06 import CATALOG_NAMES, Handler, ROOT, build_state, read_env


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "run_id", "task_id", "condition", "repetition", "transport", "agent", "ground_truth_sha256", "scoring_policy_sha256"}
    if manifest.get("schema_version") != "1.0" or not required <= set(manifest):
        raise RuntimeError("invalid Phase 07 run manifest")
    if manifest["condition"] not in CATALOG_NAMES or manifest["transport"] not in {"direct-browser", "local-gateway"}:
        raise RuntimeError("invalid condition or transport")
    if not isinstance(manifest["repetition"], int) or manifest["repetition"] < 1:
        raise RuntimeError("repetition must be a positive integer")
    if not isinstance(manifest["agent"], dict) or not manifest["agent"].get("model"):
        raise RuntimeError("agent model metadata is required")
    for field in ("ground_truth_sha256", "scoring_policy_sha256"):
        value = manifest[field]
        if not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value.lower()):
            raise RuntimeError(f"{field} must be a SHA-256 hex digest")
    return manifest


def build_phase07_state(args: argparse.Namespace) -> dict:
    manifest = load_manifest(args.run_manifest)
    state = build_state(manifest["condition"], args.frontend_root, args.catalog_dir, args.bindings, args.env, manifest["transport"])
    env = read_env(args.env)
    key = env.get("HMAC_KEY") or env.get("PHASE07_HMAC_KEY", "")
    run_id = manifest["run_id"]
    if not isinstance(run_id, str) or not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in run_id):
        raise RuntimeError("run_id must be a filesystem-safe identifier")
    manifest = {
        **manifest,
        "model": state["bindings"]["model"],
        "catalog_sha256": state["catalog"]["artifactSha256"],
        "runtime_sha256": state["bindings"]["artifactSha256"],
        "source_evidence_ids": sorted({operation["binding"]["source_evidence_id"] for operation in state["bindings"]["operations"].values()}),
    }
    logger = ExperimentLogWriter(args.log_dir / f"{run_id}.jsonl", manifest, key)
    state["experiment_logger"] = logger
    state["run_manifest"] = manifest
    state["config"]["experiment"] = {
        "schema_version": "1.0",
        "run_id": run_id,
        "task_id": manifest["task_id"],
        "condition": manifest["condition"],
        "repetition": manifest["repetition"],
        "endpoint": "/api/experiment/events",
    }
    return state


def main() -> int:
    parser = argparse.ArgumentParser(prog="serve_phase07")
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--frontend-root", type=Path, default=ROOT / "frontend" / "dist")
    parser.add_argument("--catalog-dir", type=Path, default=ROOT / "build" / "phase-05")
    parser.add_argument("--bindings", type=Path, default=ROOT / "build" / "phase-06" / "runtime-bindings.json")
    parser.add_argument("--env", type=Path, default=ROOT / ".env")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "build" / "phase-07" / "runs")
    args = parser.parse_args()
    state = build_phase07_state(args)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.runtime_state = state  # type: ignore[attr-defined]
    print(json.dumps({"run_id": state["run_manifest"]["run_id"], "task_id": state["run_manifest"]["task_id"], "condition": state["run_manifest"]["condition"], "host": args.host, "port": args.port}, ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
