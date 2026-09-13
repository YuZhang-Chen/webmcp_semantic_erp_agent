from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.browser_sap_field_probe import (
    merge_field_validations,
    metadata_summary,
    service_root,
    v2_object,
    validate_sanitized_field_evidence,
)


DELIVERY_METADATA = """
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"
 xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" Version="1.0">
  <edmx:DataServices m:DataServiceVersion="2.0">
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="API">
      <EntityType Name="A_OutbDeliveryHeaderType">
        <Property Name="DeliveryDocument" Type="Edm.String" MaxLength="10" />
        <Property Name="ActualGoodsMovementDate" Type="Edm.DateTime" />
        <Property Name="OverallGoodsMovementStatus" Type="Edm.String" MaxLength="1" />
      </EntityType>
      <EntityContainer Name="API">
        <EntitySet Name="A_OutbDeliveryHeader" EntityType="API.A_OutbDeliveryHeaderType" />
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""


def valid_payload() -> dict:
    return {
        "evidence_version": "2.0",
        "classification": "sanitized-field-evidence",
        "evidence": [
            {
                "source_evidence_id": "sap-odata-v2-fields-aaaaaaaaaaaaaaaa",
                "source_id": "webmcp.sap_sd.odata",
                "service_id": "delivery_billing_services",
                "protocol": "odata-v2",
                "odata_version": "2.0",
                "metadata_sha256": "a" * 64,
                "status": "partially_verified",
                "service_metadata": {
                    "delivery": {
                        "entity_set": "A_OutbDeliveryHeader",
                        "entity_type": "A_OutbDeliveryHeaderType",
                        "metadata_sha256": "b" * 64,
                        "properties": [
                            {"name": "DeliveryDocument", "edm_type": "Edm.String", "max_length": 10},
                            {"name": "ActualGoodsMovementDate", "edm_type": "Edm.DateTime", "max_length": None},
                            {"name": "OverallGoodsMovementStatus", "edm_type": "Edm.String", "max_length": 1},
                        ],
                    },
                    "billing": {
                        "entity_set": "A_BillingDocument",
                        "entity_type": "A_BillingDocumentType",
                        "metadata_sha256": "c" * 64,
                        "properties": [
                            {"name": "BillingDocument", "edm_type": "Edm.String", "max_length": 10},
                            {"name": "BillingDocumentDate", "edm_type": "Edm.DateTime", "max_length": None},
                            {"name": "AccountingPostingStatus", "edm_type": "Edm.String", "max_length": 1},
                        ],
                    },
                },
                "field_validations": [
                    {
                        "case_kind": "delivery_completed",
                        "service": "delivery",
                        "query_status": "passed",
                        "returned_object": True,
                        "date_present": True,
                        "status_code": "C",
                        "status_business_value": "completed",
                        "semantic_confirmation": {
                            "method": "known_document_cross_check",
                            "confirmed_by_role": "researcher_with_sap_ui",
                            "confirmed_at": "2026-09-13T00:00:00Z",
                        },
                    }
                ],
            }
        ],
    }


def test_service_root_requires_the_expected_v2_service():
    assert service_root(
        "https://sap.invalid/sap/opu/odata/sap/API_OUTBOUND_DELIVERY_SRV",
        "API_OUTBOUND_DELIVERY_SRV",
    ).endswith("API_OUTBOUND_DELIVERY_SRV/")
    with pytest.raises(RuntimeError, match="absolute HTTPS"):
        service_root("http://sap.invalid/API_OUTBOUND_DELIVERY_SRV", "API_OUTBOUND_DELIVERY_SRV")
    with pytest.raises(RuntimeError, match="credentials"):
        service_root("https://user:pass@sap.invalid/API_OUTBOUND_DELIVERY_SRV", "API_OUTBOUND_DELIVERY_SRV")
    with pytest.raises(RuntimeError, match="must end"):
        service_root("https://sap.invalid/API_SALES_ORDER_SRV", "API_OUTBOUND_DELIVERY_SRV")


def test_metadata_summary_requires_entity_and_fields():
    summary = metadata_summary(
        DELIVERY_METADATA,
        "A_OutbDeliveryHeader",
        ("DeliveryDocument", "ActualGoodsMovementDate", "OverallGoodsMovementStatus"),
    )
    assert summary["version"] == "2.0"
    assert summary["entity_type"] == "A_OutbDeliveryHeaderType"
    assert {item["name"] for item in summary["properties"]} == {
        "DeliveryDocument",
        "ActualGoodsMovementDate",
        "OverallGoodsMovementStatus",
    }
    with pytest.raises(ValueError, match="missing required"):
        metadata_summary(DELIVERY_METADATA, "A_OutbDeliveryHeader", ("BillingDocumentDate",))


def test_metadata_summary_rejects_non_v2_service():
    metadata = DELIVERY_METADATA.replace('m:DataServiceVersion="2.0"', 'm:DataServiceVersion="4.0"')
    with pytest.raises(ValueError, match="not OData V2"):
        metadata_summary(metadata, "A_OutbDeliveryHeader", ("DeliveryDocument",))


def test_v2_single_object_normalization_rejects_collection():
    assert v2_object('{"d":{"DeliveryDocument":"80000001"}}')["DeliveryDocument"] == "80000001"
    with pytest.raises(ValueError, match="single object"):
        v2_object('{"d":{"results":[{"DeliveryDocument":"80000001"}]}}')


def test_sanitized_field_evidence_is_accepted():
    validate_sanitized_field_evidence(valid_payload())


@pytest.mark.parametrize("forbidden_key", ["document_id", "endpoint", "raw_rows", "password"])
def test_field_evidence_rejects_sensitive_material(forbidden_key: str):
    payload = deepcopy(valid_payload())
    payload["evidence"][0][forbidden_key] = "forbidden"
    with pytest.raises(ValueError, match="forbidden"):
        validate_sanitized_field_evidence(payload)


def test_field_evidence_requires_true_semantic_confirmation():
    payload = valid_payload()
    payload["evidence"][0]["field_validations"][0]["semantic_confirmation"] = False
    with pytest.raises(ValueError, match="semantic confirmation"):
        validate_sanitized_field_evidence(payload)


def test_multi_case_merge_preserves_prior_statuses():
    existing = valid_payload()
    incoming = deepcopy(existing)
    incoming_case = incoming["evidence"][0]["field_validations"][0]
    incoming_case.update(
        case_kind="delivery_not_started",
        date_present=False,
        status_code="A",
        status_business_value="not_started",
    )

    merge_field_validations(incoming, existing)
    validate_sanitized_field_evidence(incoming)

    cases = incoming["evidence"][0]["field_validations"]
    assert [(case["status_code"], case["status_business_value"]) for case in cases] == [
        ("A", "not_started"),
        ("C", "completed"),
    ]


def test_multi_case_merge_migrates_v1_legacy_evidence():
    existing = valid_payload()
    record = existing["evidence"][0]
    record["verified_at"] = "2026-09-13T00:00:00Z"
    record.pop("service_metadata")
    record.pop("field_validations")
    record["observations"] = {
        "delivery": {
            "query_status": "passed",
            "returned_object": True,
            "actual_goods_movement_date_present": True,
            "status_code": "C",
            "status_business_value": "completed",
            "semantic_confirmation": True,
        },
        "billing": {
            "query_status": "passed",
            "returned_object": True,
            "billing_document_date_present": True,
            "status_code": "C",
            "status_business_value": "completely_processed",
            "semantic_confirmation": True,
        },
    }
    incoming = valid_payload()
    incoming["evidence"][0]["field_validations"][0].update(
        case_kind="delivery_not_started",
        date_present=False,
        status_code="A",
        status_business_value="not_started",
    )

    validate_sanitized_field_evidence(existing)
    merge_field_validations(incoming, existing)

    cases = incoming["evidence"][0]["field_validations"]
    assert {(case["service"], case["status_code"]) for case in cases} == {
        ("delivery", "A"),
        ("delivery", "C"),
        ("billing", "C"),
    }


def test_multi_case_merge_rejects_conflicting_code_mapping():
    existing = valid_payload()
    incoming = deepcopy(existing)
    incoming["evidence"][0]["field_validations"][0].update(
        case_kind="delivery_other",
        status_business_value="other",
    )
    with pytest.raises(ValueError, match="conflicting delivery mapping"):
        merge_field_validations(incoming, existing)


def test_multi_case_merge_rejects_metadata_change():
    existing = valid_payload()
    incoming = deepcopy(existing)
    incoming["evidence"][0]["metadata_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="metadata changed"):
        merge_field_validations(incoming, existing)
