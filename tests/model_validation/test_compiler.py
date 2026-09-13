from __future__ import annotations

import json
from copy import deepcopy

from semantic_model.compiler import artifact_bytes, compile_catalog, verify_artifact_hash
from semantic_model.validator import validate_model


def test_compiler_emits_four_public_c_tools(compilable_pair, schema):
    model, evidence, official = compilable_pair
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert result.ok, [issue.render() for issue in result.issues]
    artifact = compile_catalog(model)

    assert artifact["condition"] == "C"
    assert [tool["name"] for tool in artifact["tools"]] == sorted(
        [
            "search_sales_orders",
            "get_sales_order",
            "get_related_deliveries",
            "get_related_billing_documents",
        ]
    )
    assert verify_artifact_hash(artifact)
    rendered = json.dumps(artifact, ensure_ascii=False)
    assert "entity_set" not in rendered
    assert "metadata_sha256" not in rendered
    assert "endpoint" not in rendered


def test_compiler_is_deterministic_and_hash_changes_on_semantic_change(compilable_pair):
    model, _evidence, _official = compilable_pair
    first = compile_catalog(model)
    reordered = dict(reversed(list(deepcopy(model).items())))
    second = compile_catalog(reordered)
    assert artifact_bytes(first) == artifact_bytes(second)

    changed = deepcopy(model)
    changed["operations"]["get_sales_order"]["purpose"] += "（研究原型）"
    changed_artifact = compile_catalog(changed)
    assert changed_artifact["artifactSha256"] != first["artifactSha256"]


def test_compiler_bundles_output_schema_definitions(compilable_pair):
    model, _evidence, _official = compilable_pair
    artifact = compile_catalog(model)
    for tool in artifact["tools"]:
        output_schema = tool["outputSchema"]
        assert output_schema["$defs"]
        refs = set()

        def collect(value):
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str) and ref.startswith("#/$defs/"):
                    refs.add(ref.removeprefix("#/$defs/"))
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(output_schema)
        assert refs <= set(output_schema["$defs"])


def test_parameter_descriptions_are_required_for_compilation(
    compilable_pair, schema
):
    model, evidence, official = compilable_pair
    del model["operations"]["get_sales_order"]["input_schema"]["properties"]["sales_order_id"]["description"]
    result = validate_model(model, evidence, schema, official_evidence=official)
    assert "E_PARAMETER_DESCRIPTION" in result.codes()
