from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiment.monthly_candidates import month_bounds, monthly_path, scan_month, summarize_months


def _document(month: str, order_ids: list[str]) -> dict:
    first, last = month_bounds(month)
    return {
        "schema_version": "1.0",
        "classification": "candidate",
        "source_id": "webmcp.sap_sd.odata",
        "runtime_artifact_sha256": "a" * 64,
        "scan": {"criteria": {"order_date_from": first, "order_date_to": last}, "limit": 30, "request_count": 3},
        "candidates": [{"sales_order": {"sales_order_id": order}, "deliveries": [], "billings": [], "d3_unique_search": None} for order in order_ids],
        "failures": [],
    }


def test_month_bounds_are_calendar_correct_and_reject_future_or_other_year():
    assert month_bounds("2026-02") == ("2026-02-01", "2026-02-28")
    assert month_bounds("2026-01") == ("2026-01-01", "2026-01-31")
    with pytest.raises(ValueError, match="2026"):
        month_bounds("2025-12")
    with pytest.raises(ValueError, match="future"):
        month_bounds("2026-12")


def test_monthly_summary_counts_distinct_private_candidates_without_exposing_ids(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    for month, ids in (("2026-01", ["synthetic-1", "synthetic-2"]), ("2026-02", []), ("2026-03", ["synthetic-2", "synthetic-3"])):
        monthly_path(private_dir, month).write_text(json.dumps(_document(month, ids)), encoding="utf-8")
    summary = summarize_months(private_dir)
    assert summary["scanned_months"] == ["2026-01", "2026-02", "2026-03"]
    assert summary["candidate_count"] == 4
    assert summary["distinct_candidate_orders"] == 3
    assert summary["months"][1]["candidate_count"] == 0
    assert summary["months"][2]["overlap_with_previous_months"] == 1
    assert "synthetic-1" not in json.dumps(summary)


def test_scan_month_refuses_to_overwrite_existing_month_before_connecting(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    existing = monthly_path(private_dir, "2026-01")
    existing.write_text("existing researcher evidence", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        scan_month("2026-01", private_dir=private_dir, env=tmp_path / ".env", bindings=tmp_path / "bindings.json")
    assert existing.read_text(encoding="utf-8") == "existing researcher evidence"


def test_summary_rejects_wrong_month_criteria(tmp_path: Path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    wrong = _document("2026-02", ["synthetic-1"])
    monthly_path(private_dir, "2026-01").write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(ValueError, match="criteria mismatch"):
        summarize_months(private_dir)
