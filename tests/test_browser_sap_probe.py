from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.browser_sap_probe import (
    merge_case_validations,
    merge_sales_order_status_validations,
    service_url,
    validate_sanitized_evidence,
)


def valid_payload():
    return {
        "evidence_version": "2.0",
        "classification": "sanitized-build-metadata",
        "evidence": [
            {
                "source_evidence_id": "sap-odata-v2-aaaaaaaaaaaaaaaa",
                "source_id": "webmcp.sap_sd.odata",
                "service_id": "sales_order_service",
                "protocol": "odata-v2",
                "odata_version": "2.0",
                "verified_at": "2026-09-13T00:00:00Z",
                "metadata_sha256": "a" * 64,
                "status": "partially_verified",
                "observations": {"entity_sets": [{"name": "A_SalesOrder"}]},
                "smoke_tests": {"metadata_get": "passed"},
            }
        ],
    }


def test_v2_service_selector_requires_https_base():
    assert service_url("https://sap.invalid/sap/opu/odata/sap") == "https://sap.invalid/sap/opu/odata/sap/API_SALES_ORDER_SRV/"
    assert service_url("https://sap.invalid") == "https://sap.invalid/API_SALES_ORDER_SRV/"
    with pytest.raises(RuntimeError, match="credentials"):
        service_url("https://user:pass@sap.invalid/odata/v4/0001")


def valid_case(case_kind="pgi_posted"):
    mappings = [{"category_code": "X", "business_value": "outbound_delivery"}]
    if case_kind == "full_sales_flow":
        mappings.append({"category_code": "Y", "business_value": "billing_document"})
    return {
        "case_kind": case_kind,
        "query_status": "passed",
        "returned_rows": True,
        "category_mappings": mappings,
        "semantic_confirmation": {
            "method": "known_case_cross_check",
            "confirmed_by_role": "researcher_with_sap_ui",
            "confirmed_at": "2026-09-13T00:00:00Z",
        },
    }


def test_sanitized_evidence_is_accepted():
    validate_sanitized_evidence(valid_payload())


def test_v4_evidence_is_rejected_after_v2_cutover():
    payload = valid_payload()
    record = payload["evidence"][0]
    record["source_evidence_id"] = "sap-odata-v4-aaaaaaaaaaaaaaaa"
    record["protocol"] = "odata-v4"
    record["odata_version"] = "4.0"
    with pytest.raises(ValueError, match="unexpected source or protocol"):
        validate_sanitized_evidence(payload)


def test_endpoint_material_is_rejected():
    payload = deepcopy(valid_payload())
    payload["evidence"][0]["observations"]["bad"] = "https://tenant.example"
    with pytest.raises(ValueError, match="forbidden"):
        validate_sanitized_evidence(payload)


@pytest.mark.parametrize("forbidden_key", ["username", "password", "authorization", "business_key"])
def test_sensitive_keys_are_rejected(forbidden_key):
    payload = deepcopy(valid_payload())
    payload["evidence"][0]["observations"][forbidden_key] = "redacted"
    with pytest.raises(ValueError, match="forbidden"):
        validate_sanitized_evidence(payload)


def test_legitimate_metadata_identifier_is_not_treated_as_a_secret():
    payload = deepcopy(valid_payload())
    payload["evidence"][0]["observations"]["properties"] = ["AuthorizationGroup"]
    validate_sanitized_evidence(payload)


def test_two_sanitized_known_cases_are_accepted():
    payload = valid_payload()
    payload["evidence"][0]["case_validations"] = [
        valid_case("pgi_posted"),
        valid_case("full_sales_flow"),
    ]
    validate_sanitized_evidence(payload)


def valid_sales_order_status(code="C", value="completed", case_kind="pgi_posted"):
    return {
        "case_kind": case_kind,
        "query_status": "passed",
        "returned_object": True,
        "status_code": code,
        "status_business_value": value,
        "semantic_confirmation": {
            "method": "known_case_cross_check",
            "confirmed_by_role": "researcher_with_sap_ui",
            "confirmed_at": "2026-09-13T00:00:00Z",
        },
    }


def test_sales_order_status_case_is_accepted_and_sanitized():
    payload = valid_payload()
    payload["evidence"][0]["sales_order_status_validations"] = [
        valid_sales_order_status()
    ]
    validate_sanitized_evidence(payload)


def test_sales_order_status_case_conflict_is_rejected():
    payload = valid_payload()
    payload["evidence"][0]["sales_order_status_validations"] = [
        valid_sales_order_status(),
        valid_sales_order_status("C", "partially_completed", "full_sales_flow"),
    ]
    with pytest.raises(ValueError, match="conflicting meanings"):
        validate_sanitized_evidence(payload)


def test_sales_order_status_cases_survive_page_reload():
    existing = valid_payload()
    existing["evidence"][0]["sales_order_status_validations"] = [valid_sales_order_status()]
    incoming = valid_payload()
    incoming["evidence"][0]["sales_order_status_validations"] = [
        valid_sales_order_status("A", "not_started", "full_sales_flow")
    ]
    merge_sales_order_status_validations(incoming, existing)
    assert [
        case["status_code"]
        for case in incoming["evidence"][0]["sales_order_status_validations"]
    ] == ["A", "C"]


def test_saved_known_cases_survive_page_reload():
    existing = valid_payload()
    existing["evidence"][0]["case_validations"] = [valid_case("pgi_posted")]
    incoming = valid_payload()
    incoming["evidence"][0]["case_validations"] = [valid_case("full_sales_flow")]

    merge_case_validations(incoming, existing)

    cases = incoming["evidence"][0]["case_validations"]
    assert [case["case_kind"] for case in cases] == ["pgi_posted", "full_sales_flow"]
    validate_sanitized_evidence(incoming)


def test_known_cases_are_not_reused_after_metadata_changes():
    existing = valid_payload()
    existing["evidence"][0]["case_validations"] = [valid_case("pgi_posted")]
    incoming = valid_payload()
    incoming["evidence"][0]["metadata_sha256"] = "b" * 64

    merge_case_validations(incoming, existing)

    assert "case_validations" not in incoming["evidence"][0]


def test_case_business_identifier_is_rejected():
    payload = valid_payload()
    case = valid_case()
    case["document_id"] = "redacted"
    payload["evidence"][0]["case_validations"] = [case]
    with pytest.raises(ValueError, match="unknown or missing"):
        validate_sanitized_evidence(payload)


def test_full_sales_flow_requires_billing_category():
    payload = valid_payload()
    case = valid_case("full_sales_flow")
    case["category_mappings"] = [
        {"category_code": "X", "business_value": "outbound_delivery"}
    ]
    payload["evidence"][0]["case_validations"] = [case]
    with pytest.raises(ValueError, match="billing document"):
        validate_sanitized_evidence(payload)


def test_category_code_cannot_change_business_meaning_between_cases():
    payload = valid_payload()
    first = valid_case("pgi_posted")
    second = valid_case("full_sales_flow")
    second["category_mappings"] = [
        {"category_code": "X", "business_value": "billing_document"},
        {"category_code": "Y", "business_value": "outbound_delivery"},
    ]
    payload["evidence"][0]["case_validations"] = [first, second]
    with pytest.raises(ValueError, match="conflicting business meanings"):
        validate_sanitized_evidence(payload)
