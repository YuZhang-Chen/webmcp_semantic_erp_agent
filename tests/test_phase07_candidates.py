import copy
import json
from pathlib import Path

import pytest

from experiment.candidates import CandidateScanner, verify_artifact


ROOT = Path(__file__).resolve().parents[1]


def artifact():
    return json.loads((ROOT / "build" / "phase-06" / "runtime-bindings.json").read_text(encoding="utf-8"))


class FakeTransport:
    def __init__(self):
        self.orders = [
            {"SalesOrder": "10001", "SoldToParty": "C01", "SalesOrderDate": "2026-01-01T00:00:00", "OverallSDProcessStatus": "C"},
            {"SalesOrder": "10002", "SoldToParty": "C02", "SalesOrderDate": "2026-01-02T00:00:00", "OverallSDProcessStatus": "C"},
            {"SalesOrder": "10003", "SoldToParty": "C03", "SalesOrderDate": "2026-01-03T00:00:00", "OverallSDProcessStatus": "B"},
            {"SalesOrder": "10004", "SoldToParty": "C04", "SalesOrderDate": "2026-01-04T00:00:00", "OverallSDProcessStatus": "C"},
            {"SalesOrder": "10005", "SoldToParty": "C05", "SalesOrderDate": "2026-01-05T00:00:00", "OverallSDProcessStatus": "C"},
        ]

    def get_json(self, service_id, entity_set, params):
        if entity_set == "A_SalesOrder":
            if params.get("$top") == "2" and "SalesOrderDate" in params.get("$filter", ""):
                # D3 uniqueness probes: exact dates identify one order.
                date = params.get("$filter", "")
                rows = [row for row in self.orders if row["SalesOrderDate"][:10] in date]
            elif "SalesOrder eq" in params.get("$filter", ""):
                rows = [row for row in self.orders if row["SalesOrder"] in params.get("$filter", "")]
            else:
                rows = self.orders
            return {"d": {"results": rows[: int(params.get("$top", 30))]}}
        if entity_set == "A_SalesOrderItmSubsqntProcFlow":
            order = next((row["SalesOrder"] for row in self.orders if row["SalesOrder"] in params.get("$filter", "")), "")
            if "'J'" in params.get("$filter", ""):
                rows = [{"SalesOrder": order, "SubsequentDocument": f"8{order}"}] if order in {"10001", "10002", "10004", "10005"} else []
            else:
                rows = [{"SalesOrder": order, "SubsequentDocument": f"9{order}"}] if order in {"10001", "10002"} else []
            return {"d": {"results": rows}}
        if entity_set == "A_OutbDeliveryHeader":
            return {"d": {"results": [{"DeliveryDocument": "810001", "ActualGoodsMovementDate": "2026-01-04T00:00:00", "OverallGoodsMovementStatus": "C"}]}}
        if entity_set == "A_BillingDocument":
            return {"d": {"results": [{"BillingDocument": "910001", "BillingDocumentDate": "2026-01-05T00:00:00", "AccountingPostingStatus": "C"}]}}
        raise AssertionError(entity_set)

    def get_next_json(self, service_id, next_url):
        raise AssertionError("pagination is not expected in this fixture")


def test_candidate_scan_assigns_five_slots_only_when_evidence_exists():
    result = CandidateScanner(artifact(), FakeTransport(), delay_ms=0).scan({"order_status": "completed"}, limit=10)
    assert result["classification"] == "candidate"
    assert result["suggested_assignments"]["P05"] is not None
    assert result["suggested_assignments"]["P03"] is not None
    assert result["suggested_assignments"]["P04"] is not None
    assert result["suggested_assignments"]["P02"] is not None
    assert result["suggested_assignments"]["P01"] is not None
    assert all("approved" not in candidate for candidate in result["candidates"])


def test_limit_is_bounded_and_artifact_is_verified():
    assert verify_artifact(artifact())
    with pytest.raises(ValueError, match="between 10 and 30"):
        CandidateScanner(artifact(), FakeTransport(), delay_ms=0).scan({"order_status": "completed"}, limit=31)


def test_tampered_artifact_is_rejected():
    value = copy.deepcopy(artifact())
    value["model"]["version"] = "tampered"
    with pytest.raises(ValueError, match="hash verification"):
        CandidateScanner(value, FakeTransport(), delay_ms=0)
