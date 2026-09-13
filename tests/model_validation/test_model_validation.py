from __future__ import annotations

from copy import deepcopy

import pytest

from semantic_model.canonicalizer import canonical_model_bytes, model_sha256
from semantic_model.validator import validate_arguments, validate_model


def test_checked_in_draft_is_structurally_valid(draft_model, draft_evidence, official_evidence, schema):
    result = validate_model(draft_model, draft_evidence, schema, official_evidence=official_evidence, require_compilable=False)
    assert result.ok, [issue.render() for issue in result.issues]


def test_multi_source_validation_requires_official_release_evidence(draft_model, draft_evidence, schema):
    result = validate_model(draft_model, draft_evidence, schema, require_compilable=False)
    assert "E_MISSING_OFFICIAL_EVIDENCE" in result.codes()


def test_official_release_must_match_s4hana_2023_s4core_108(
    draft_model, draft_evidence, official_evidence, schema
):
    official = deepcopy(official_evidence)
    official["baseline"]["component_release"] = "109"
    result = validate_model(
        draft_model,
        draft_evidence,
        schema,
        official_evidence=official,
        require_compilable=False,
    )
    assert "E_RELEASE_BASELINE_MISMATCH" in result.codes()


def test_reference_only_official_status_domain_fails_strict_gate(
    draft_model, draft_evidence, official_evidence, schema
):
    official_evidence = deepcopy(official_evidence)
    official_evidence["services"][2]["status_domains"]["AccountingPostingStatus"]["completeness"] = "reference_only"
    result = validate_model(
        draft_model,
        draft_evidence,
        schema,
        official_evidence=official_evidence,
    )
    assert "E_OFFICIAL_STATUS_DOMAIN_INCOMPLETE" in result.codes()


def test_officially_documented_delivery_b_does_not_require_tenant_case(
    compilable_pair, schema
):
    model, evidence, official = compilable_pair
    delivery_domain = official["services"][0]["status_domains"]["OverallGoodsMovementStatus"]
    delivery_domain["values"] = {
        "A": "active",
        "B": "partially_completed",
        "C": "completed",
    }
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_STATUS_REPRESENTATIVE_CASE" not in result.codes()
    assert "E_STATUS_REPRESENTATIVE_MISMATCH" not in result.codes()


def test_checked_in_tenant_evidence_contains_sanitized_delivery_and_billing_fields(draft_evidence):
    records = {
        record["source_evidence_id"]: record
        for record in draft_evidence["evidence"]
    }
    field_record = records["sap-odata-v2-fields-83f4491577c97838"]
    delivery = field_record["observations"]["delivery"]
    billing = field_record["observations"]["billing"]

    assert delivery["status_code"] == "C"
    assert delivery["status_business_value"] == "completed"
    assert billing["status_code"] == "C"
    assert billing["status_business_value"] == "completely_processed"
    assert "document_id" not in field_record


def test_business_field_candidate_is_governed(draft_model, draft_evidence, official_evidence, schema):
    model = deepcopy(draft_model)
    model["business_fields"]["delivery_date"]["candidate_property"] = "CreationDate"

    result = validate_model(model, draft_evidence, schema, official_evidence=official_evidence, require_compilable=False)

    assert "E_BUSINESS_FIELD_CANDIDATE" in result.codes()


def test_checked_in_draft_is_rejected_by_compilation_gate(draft_model, draft_evidence, official_evidence, schema):
    draft_model = deepcopy(draft_model)
    draft_model["model"]["status"] = "draft"
    result = validate_model(draft_model, draft_evidence, schema, official_evidence=official_evidence)
    assert not result.ok
    assert result.codes() == {"E_MODEL_NOT_VALIDATED"}


def test_v2_delivery_billing_bindings_are_tenant_verified(draft_model, draft_evidence, official_evidence, schema):
    result = validate_model(draft_model, draft_evidence, schema, official_evidence=official_evidence)
    related_paths = {
        issue.path
        for issue in result.issues
        if issue.code in {"E_UNVERIFIED_BINDING", "E_ENTITY_SET_BINDING"}
        and ("get_related_deliveries_binding" in issue.path or "get_related_billing_documents_binding" in issue.path)
    }
    assert not related_paths


def test_missing_document_flow_known_case_fails_strict_gate(compilable_pair, schema):
    model, evidence, official = compilable_pair
    evidence["evidence"][0]["case_validations"] = []
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_DISCRIMINATOR_CASE_EVIDENCE" in result.codes()


def test_tenant_field_type_mismatch_fails_strict_gate(compilable_pair, schema):
    model, evidence, official = compilable_pair
    metadata = evidence["evidence"][0]["observations"]["document_flow_options"]
    sales_order = next(
        item for item in metadata if item["entitySet"] == "Test_get_sales_order_binding"
    )
    property_item = next(
        item for item in sales_order["properties"] if item["name"] == "Test_sales_order_id"
    )
    property_item["edm_type"] = "Edm.Int32"
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_TENANT_FIELD_TYPE" in result.codes()


def test_missing_enrichment_representative_case_fails_strict_gate(compilable_pair, schema):
    model, evidence, official = compilable_pair
    evidence["evidence"][0]["field_validations"] = [
        case
        for case in evidence["evidence"][0]["field_validations"]
        if case["service"] != "billing"
    ]
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_ENRICHMENT_CASE_EVIDENCE" in result.codes()


def test_fully_evidenced_model_passes_compilation_gate(compilable_pair, schema):
    model, evidence, official = compilable_pair
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert result.ok, [issue.render() for issue in result.issues]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda model: model["operations"]["get_sales_order"].update(method="POST"), "E_NON_GET_OPERATION"),
        (lambda model: model["relationships"]["customer_places_sales_order"].update(source="missing"), "E_UNKNOWN_ENTITY"),
        (lambda model: model["operations"]["get_sales_order"].update(output_schema_ref="missing"), "E_UNKNOWN_OUTPUT_SCHEMA"),
        (lambda model: model["operations"]["get_sales_order"].update(binding_ref="missing"), "E_MISSING_BINDING"),
    ],
)
def test_invalid_model_is_rejected(compilable_pair, schema, mutate, expected_code):
    model, evidence, official = compilable_pair
    mutate(model)
    assert expected_code in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_unknown_operation_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["operations"]["delete_sales_order"] = deepcopy(model["operations"]["get_sales_order"])
    assert "E_UNKNOWN_OPERATION" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_unknown_parameter_is_rejected_at_build_time(compilable_pair, schema):
    model, evidence, official = compilable_pair
    properties = model["operations"]["get_sales_order"]["input_schema"]["properties"]
    properties["debug"] = {"type": "string"}
    assert "E_PARAMETER_SET" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_unverified_field_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["bindings"]["get_sales_order_binding"]["parameters"]["sales_order_id"]["status"] = "unverified"
    assert "E_UNVERIFIED_FIELD_BINDING" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_metadata_hash_mismatch_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["bindings"]["get_sales_order_binding"]["metadata_sha256"] = "b" * 64
    assert "E_METADATA_HASH_MISMATCH" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_related_document_discriminator_must_be_verified(compilable_pair, schema):
    model, evidence, official = compilable_pair
    discriminator = model["bindings"]["get_related_deliveries_binding"]["discriminator"]
    discriminator["status"] = "unverified"
    assert "E_UNVERIFIED_DISCRIMINATOR" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_related_document_requires_composite_enrichment(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["bindings"]["get_related_deliveries_binding"].pop("enrichment")
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_MISSING_ENRICHMENT" in result.codes()


def test_enrichment_field_must_match_scoped_metadata(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["bindings"]["get_related_deliveries_binding"]["output_fields"]["delivery_status"]["property"] = "Test_MissingStatus"
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_ENRICHMENT_FIELD_PROPERTY" in result.codes()


def test_unverified_enrichment_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    binding = model["bindings"]["get_related_deliveries_binding"]
    binding["enrichment"]["status"] = "partially_verified"
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_UNVERIFIED_ENRICHMENT" in result.codes()


def test_status_without_governed_code_map_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    field = model["bindings"]["search_sales_orders_binding"]["parameters"]["order_status"]
    field["code_map"] = None
    assert "E_MISSING_STATUS_CODE_MAP" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_parameter_length_must_match_tenant_metadata(compilable_pair, schema):
    model, evidence, official = compilable_pair
    properties = model["operations"]["get_sales_order"]["input_schema"]["properties"]
    properties["sales_order_id"]["maxLength"] = 10
    assert "E_PARAMETER_LENGTH_MISMATCH" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_status_enum_must_match_governed_code_map(compilable_pair, schema):
    model, evidence, official = compilable_pair
    properties = model["operations"]["search_sales_orders"]["input_schema"]["properties"]
    properties["criteria"]["properties"]["order_status"]["enum"] = ["wrong"]
    assert "E_STATUS_ENUM_MISMATCH" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_output_status_enum_must_match_governed_code_map(compilable_pair, schema):
    model, evidence, official = compilable_pair
    output = model["output_schemas"]["$defs"]["sales_order_summary"]["properties"]
    output["order_status"]["enum"] = ["wrong", None]
    assert "E_OUTPUT_STATUS_ENUM_MISMATCH" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_invalid_embedded_json_schema_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["operations"]["get_sales_order"]["input_schema"]["type"] = "not-a-json-type"
    assert "E_INVALID_JSON_SCHEMA" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_private_output_field_is_rejected(compilable_pair, schema):
    model, evidence, official = compilable_pair
    model["output_schemas"]["sales_order_detail"]["properties"]["endpoint"] = {"type": "string"}
    assert "E_PRIVATE_OUTPUT_FIELD" in validate_model(model, evidence, schema, official_evidence=official).codes()


def test_runtime_arguments_reject_unknown_property(draft_model):
    operation = draft_model["operations"]["get_sales_order"]
    result = validate_arguments(operation, {"sales_order_id": "1", "debug": True})
    assert "E_ARGUMENT_SCHEMA" in result.codes()


def test_runtime_search_requires_non_empty_criteria(draft_model):
    operation = draft_model["operations"]["search_sales_orders"]
    result = validate_arguments(operation, {"criteria": {}})
    assert "E_EMPTY_SEARCH_CRITERIA" in result.codes()


def test_runtime_search_rejects_reversed_date_range(draft_model):
    operation = draft_model["operations"]["search_sales_orders"]
    result = validate_arguments(
        operation,
        {"criteria": {"order_date_from": "2026-09-14", "order_date_to": "2026-09-13"}},
    )
    assert "E_INVALID_DATE_RANGE" in result.codes()


def test_model_hash_is_deterministic_and_ignores_generated_metadata(draft_model):
    reordered = dict(reversed(list(deepcopy(draft_model).items())))
    reordered["model_hash"] = "old-generated-value"
    reordered["validated_at"] = "different-every-run"
    assert canonical_model_bytes(draft_model) == canonical_model_bytes(reordered)
    assert model_sha256(draft_model) == model_sha256(reordered)
