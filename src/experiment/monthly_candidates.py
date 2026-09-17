"""Private, month-by-month discovery of Phase 08 live SAP candidates."""

from __future__ import annotations

import calendar
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .candidates import CandidateScanner, build_gateway_from_env
from .phase07 import file_sha256

MONTH = re.compile(r"^2026-(0[1-9]|1[0-2])$")


def month_bounds(month: str) -> tuple[str, str]:
    if not MONTH.fullmatch(month):
        raise ValueError("month must be YYYY-MM in 2026")
    year, number = (int(part) for part in month.split("-"))
    first = f"{month}-01"
    last = f"{month}-{calendar.monthrange(year, number)[1]:02d}"
    if first > datetime.now(UTC).date().isoformat():
        raise ValueError("cannot scan a future month")
    return first, last


def monthly_path(private_dir: Path, month: str) -> Path:
    month_bounds(month)
    return private_dir / f"{month}-candidates.json"


def candidate_summary(path: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    if document.get("classification") != "candidate" or document.get("source_id") != "webmcp.sap_sd.odata":
        raise ValueError("monthly artifact is not a live SAP candidate scan")
    candidates = document.get("candidates")
    failures = document.get("failures")
    scan = document.get("scan")
    if not isinstance(candidates, list) or not isinstance(failures, list) or not isinstance(scan, Mapping):
        raise ValueError("monthly artifact shape is invalid")
    deliveries = sum(bool(item.get("deliveries")) for item in candidates)
    billings = sum(bool(item.get("billings")) for item in candidates)
    unique_search = sum(bool(item.get("d3_unique_search")) for item in candidates)
    return {
        "month": path.name[:7],
        "classification": "candidate",
        "source_id": "webmcp.sap_sd.odata",
        "candidate_count": len(candidates),
        "failure_count": len(failures),
        "with_delivery": deliveries,
        "with_billing": billings,
        "with_unique_non_id_search": unique_search,
        "request_count": scan.get("request_count"),
        "runtime_artifact_sha256": document.get("runtime_artifact_sha256"),
        "file_sha256": file_sha256(path),
    }


def scan_month(month: str, *, private_dir: Path, env: Path, bindings: Path, limit: int = 30, delay_ms: int = 100) -> dict[str, Any]:
    start, end = month_bounds(month)
    if not 10 <= limit <= 30:
        raise ValueError("limit must be between 10 and 30")
    output = monthly_path(private_dir, month)
    if output.exists():
        raise FileExistsError(f"monthly candidate artifact already exists: {output}")
    artifact = json.loads(bindings.read_text(encoding="utf-8"))
    scanner = CandidateScanner(artifact, build_gateway_from_env(env, artifact), delay_ms=delay_ms)
    document = scanner.scan({"order_date_from": start, "order_date_to": end}, limit=limit)
    document["phase08_month"] = month
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return candidate_summary(output, document)


def summarize_months(private_dir: Path) -> dict[str, Any]:
    months: list[dict[str, Any]] = []
    seen_orders: set[str] = set()
    for path in sorted(private_dir.glob("2026-??-candidates.json")):
        month_bounds(path.name[:7])
        document = json.loads(path.read_text(encoding="utf-8"))
        scan = document.get("scan", {})
        first, last = month_bounds(path.name[:7])
        if scan.get("criteria") != {"order_date_from": first, "order_date_to": last}:
            raise ValueError(f"monthly scan criteria mismatch: {path.name}")
        summary = candidate_summary(path, document)
        orders = {str(item.get("sales_order", {}).get("sales_order_id")) for item in document["candidates"]}
        if "None" in orders or "" in orders:
            raise ValueError(f"candidate lacks an order ID: {path.name}")
        summary["new_distinct_orders"] = len(orders - seen_orders)
        summary["overlap_with_previous_months"] = len(orders & seen_orders)
        seen_orders.update(orders)
        months.append(summary)
    return {
        "classification": "candidate_summary",
        "source_id": "webmcp.sap_sd.odata",
        "scanned_months": [item["month"] for item in months],
        "distinct_candidate_orders": len(seen_orders),
        "candidate_count": sum(item["candidate_count"] for item in months),
        "failure_count": sum(item["failure_count"] for item in months),
        "months": months,
        "notice": "Live candidates require separate researcher confirmation and approval; this is not Ground Truth.",
    }
