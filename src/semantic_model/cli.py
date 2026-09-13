"""Command-line build gate for SAP SD semantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .canonicalizer import model_sha256
from .loader import load_evidence, load_json_schema, load_model
from .validator import validate_model


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semantic-model")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a governed semantic model")
    validate.add_argument("--model", type=Path, required=True)
    validate.add_argument("--evidence", type=Path, required=True)
    validate.add_argument("--official-evidence", type=Path, required=True)
    validate.add_argument("--schema", type=Path, required=True)
    validate.add_argument(
        "--allow-draft",
        action="store_true",
        help="validate structure and references without asserting compilation readiness",
    )
    validate.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    model = load_model(args.model)
    evidence = load_evidence(args.evidence)
    official_evidence = load_evidence(args.official_evidence)
    schema = load_json_schema(args.schema)
    result = validate_model(
        model,
        evidence,
        schema,
        official_evidence=official_evidence,
        require_compilable=not args.allow_draft,
    )
    report = {
        "model_id": model.get("model", {}).get("id"),
        "model_version": model.get("model", {}).get("version"),
        "model_status": model.get("model", {}).get("status"),
        "model_sha256": model_sha256(model),
        "official_evidence_id": official_evidence.get("evidence_id"),
        "release_baseline": official_evidence.get("baseline"),
        "compilation_ready": result.ok and not args.allow_draft,
        "validation_mode": "draft" if args.allow_draft else "compilation_gate",
        "issues": [
            {"code": issue.code, "path": issue.path, "message": issue.message}
            for issue in result.issues
        ],
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
