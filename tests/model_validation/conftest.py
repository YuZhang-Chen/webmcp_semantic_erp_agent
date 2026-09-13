from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from semantic_model.loader import load_evidence, load_json_schema, load_model


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "semantic_models" / "sap_sd" / "model.yaml"
SCHEMA_PATH = ROOT / "semantic_models" / "sap_sd" / "model.schema.json"
EVIDENCE_PATH = ROOT / "semantic_models" / "sap_sd" / "evidence" / "tenant-binding-evidence.json"
OFFICIAL_EVIDENCE_PATH = ROOT / "semantic_models" / "sap_sd" / "evidence" / "official-s4hana-2023.json"


@pytest.fixture
def draft_model():
    return load_model(MODEL_PATH)


@pytest.fixture
def schema():
    return load_json_schema(SCHEMA_PATH)


@pytest.fixture
def draft_evidence():
    return load_evidence(EVIDENCE_PATH)


@pytest.fixture
def official_evidence():
    return load_evidence(OFFICIAL_EVIDENCE_PATH)


@pytest.fixture
def compilable_pair(draft_model, official_evidence):
    model = deepcopy(draft_model)
    model["model"]["version"] = "0.2.0"
    model["model"]["status"] = "validated"
    for field in model["business_fields"].values():
        field["binding_status"] = "tenant_verified"
    metadata_hash = "a" * 64
    binding_ids = list(model["bindings"])
    for binding_id, binding in model["bindings"].items():
        binding["service_id"] = "test_service"
        binding["entity_set"] = f"Test_{binding_id}"
        binding["query_strategy"] = "collection_filter"
        binding["status"] = "tenant_verified"
        binding["source_evidence_id"] = "synthetic-test-evidence"
        binding["metadata_sha256"] = metadata_hash
        if binding_id in {
            "get_related_deliveries_binding",
            "get_related_billing_documents_binding",
        }:
            discriminator = binding["discriminator"]
            discriminator["property"] = "Test_SubsequentDocumentCategory"
            discriminator["status"] = "tenant_verified"
            discriminator["code_map"] = {"T": discriminator["business_value"]}
            scope = "delivery" if binding_id == "get_related_deliveries_binding" else "billing"
            key_property = "Test_DeliveryDocument" if scope == "delivery" else "Test_BillingDocument"
            binding["enrichment"] = {
                "service_id": "test_service",
                "method": "GET",
                "entity_set": f"Test_{scope.title()}Document",
                "query_strategy": "unique_filter",
                "status": "tenant_verified",
                "source_evidence_id": "synthetic-test-evidence",
                "metadata_sha256": metadata_hash,
                "key_property": key_property,
                "input_field": "delivery_id" if scope == "delivery" else "billing_document_id",
                "evidence_scope": scope,
            }
        for section in ("parameters", "output_fields"):
            for field_id, field in binding[section].items():
                field["property"] = {
                    "order_status": "OverallSDProcessStatus",
                    "delivery_status": "OverallGoodsMovementStatus",
                    "billing_status": "AccountingPostingStatus",
                }.get(field_id, f"Test_{field_id}")
                field["status"] = "tenant_verified"
                field["edm_type"] = "Edm.String"
                field["max_length"] = 40
                if field_id.endswith("status"):
                    field["code_map"] = {"A": "active"}
                    field["code_map_status"] = "official_documented"
                    field["tenant_observed_codes"] = ["A"]
        operation = next(
            item for item in model["operations"].values() if item["binding_ref"] == binding_id
        )
        properties = operation["input_schema"]["properties"]
        if binding_id == "search_sales_orders_binding":
            properties = properties["criteria"]["properties"]
        for field_id, field in binding["parameters"].items():
            properties[field_id]["maxLength"] = field["max_length"]
            if field_id.endswith("status"):
                properties[field_id]["enum"] = list(field["code_map"].values())
        definition_by_binding = {
            "search_sales_orders_binding": "sales_order_summary",
            "get_sales_order_binding": "sales_order_summary",
            "get_related_deliveries_binding": "delivery_summary",
            "get_related_billing_documents_binding": "billing_document_summary",
        }
        definition = model["output_schemas"]["$defs"][definition_by_binding[binding_id]]
        for field_id, field in binding["output_fields"].items():
            if field_id.endswith("status"):
                definition["properties"][field_id]["enum"] = [*field["code_map"].values(), None]
    scoped_properties = {}
    for scope, key_name in (("delivery", "Test_DeliveryDocument"), ("billing", "Test_BillingDocument")):
        names = {key_name}
        for binding_id, binding in model["bindings"].items():
            if binding.get("enrichment", {}).get("evidence_scope") == scope:
                names.update(
                    field.get("property")
                    for field in binding.get("output_fields", {}).values()
                    if field.get("step_ref") == "enrichment"
                )
        scoped_properties[scope] = {
            "metadata_sha256": metadata_hash,
            "properties": [
                {"name": name, "edm_type": "Edm.String", "max_length": 40}
                for name in sorted(name for name in names if name)
            ],
        }
    binding_metadata = []
    for binding in model["bindings"].values():
        metadata_by_name = {
            field["property"]: {
                "name": field["property"],
                "edm_type": field["edm_type"],
                "max_length": field.get("max_length"),
            }
            for section in ("parameters", "output_fields")
            for field in binding[section].values()
            if field.get("step_ref") != "enrichment"
        }
        if binding.get("discriminator"):
            discriminator = binding["discriminator"]
            metadata_by_name[discriminator["property"]] = {
                "name": discriminator["property"],
                "edm_type": discriminator["edm_type"],
                "max_length": discriminator.get("max_length"),
            }
        binding_metadata.append(
            {
                "entitySet": binding["entity_set"],
                "properties": [metadata_by_name[name] for name in sorted(metadata_by_name)],
            }
        )
    evidence = {
        "release_baseline": {
            "product": "SAP S/4HANA",
            "release": "2023",
            "software_component": "S4CORE",
            "component_release": "108",
        },
        "evidence_version": "test-only",
        "classification": "synthetic-test-fixture",
        "evidence": [
            {
                "source_evidence_id": "synthetic-test-evidence",
                "source_id": "webmcp.sap_sd.odata",
                "service_id": "test_service",
                "protocol": "odata-v2",
                "odata_version": "2.0",
                "verified_at": "2026-09-13T00:00:00Z",
                "metadata_sha256": metadata_hash,
                "status": "tenant_verified",
                "verified_bindings": binding_ids + [
                    "get_related_deliveries_binding:enrichment",
                    "get_related_billing_documents_binding:enrichment",
                ],
                "observations": {
                    **scoped_properties,
                    "document_flow_options": binding_metadata,
                },
                "case_validations": [
                    {
                        "query_status": "passed",
                        "returned_rows": True,
                        "category_mappings": [
                            {"category_code": "T", "business_value": "outbound_delivery"},
                            {"category_code": "U", "business_value": "billing_document"},
                        ],
                    }
                ],
                "smoke_tests": {
                    "metadata_get": "passed",
                    "sales_order_collection_get": "passed",
                    "sales_order_filter": "passed",
                },
            }
        ],
    }
    entity_sets: dict[str, list[str]] = {}
    for binding in model["bindings"].values():
        entity_sets[binding["entity_set"]] = sorted({
            field["property"]
            for section in ("parameters", "output_fields")
            for field in binding[section].values()
            if field.get("step_ref") != "enrichment"
        } | ({binding["discriminator"]["property"]} if binding.get("discriminator") else set()))
        enrichment = binding.get("enrichment")
        if enrichment:
            entity_sets[enrichment["entity_set"]] = sorted({
                enrichment["key_property"],
                *(field["property"] for field in binding["output_fields"].values() if field.get("step_ref") == "enrichment"),
            })
    complete_official_evidence = {
        "classification": "sap-official-release-evidence",
        "evidence_id": model["evidence_policy"]["official_release_evidence_id"],
        "baseline": {
            "product": "SAP S/4HANA",
            "release": "2023",
            "software_component": "S4CORE",
            "component_release": "108",
        },
        "services": [{
            "service_id": "test_service",
            "evidence_status": "official_documented",
            "operations": list(model["operations"]),
            "entity_sets": entity_sets,
            "status_domains": {
                property_name: {
                    "code_list_id": property_name,
                    "completeness": "complete",
                    "evidence_status": "official_documented",
                    "values": {"A": "active"},
                }
                for property_name in (
                    "OverallSDProcessStatus",
                    "OverallGoodsMovementStatus",
                    "AccountingPostingStatus",
                )
            },
        }],
    }
    evidence["evidence"][0]["field_validations"] = [
        {
            "service": "delivery",
            "status_code": "A",
            "status_business_value": "active",
            "query_status": "passed",
            "returned_object": True,
        },
        {
            "service": "billing",
            "status_code": "A",
            "status_business_value": "active",
            "query_status": "passed",
            "returned_object": True,
        },
    ]
    evidence["evidence"][0]["sales_order_status_validations"] = [
        {
            "status_code": "A",
            "status_business_value": "active",
            "query_status": "passed",
            "returned_object": True,
        }
    ]
    evidence["evidence"][0]["status_domain_validations"] = [
        {
            "property": "AccountingPostingStatus",
            "completeness": "complete",
            "values": {"A": {"business_value": "active"}},
        }
    ]
    return model, evidence, complete_official_evidence
