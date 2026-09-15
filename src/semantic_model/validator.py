"""Build-time semantic model and runtime canonical argument validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker

from .errors import ValidationIssue


CANONICAL_OPERATIONS = frozenset(
    {
        "search_sales_orders",
        "get_sales_order",
        "get_related_deliveries",
        "get_related_billing_documents",
    }
)
EXPECTED_PARAMETERS = {
    "search_sales_orders": frozenset(
        {"customer_id", "order_date_from", "order_date_to", "order_status"}
    ),
    "get_sales_order": frozenset({"sales_order_id"}),
    "get_related_deliveries": frozenset({"sales_order_id"}),
    "get_related_billing_documents": frozenset({"sales_order_id"}),
}
EXPECTED_OUTPUT_FIELDS = {
    "search_sales_orders": frozenset(
        {"sales_order_id", "customer_id", "order_date", "order_status"}
    ),
    "get_sales_order": frozenset(
        {"sales_order_id", "customer_id", "order_date", "order_status"}
    ),
    "get_related_deliveries": frozenset(
        {"delivery_id", "sales_order_id", "delivery_date", "delivery_status"}
    ),
    "get_related_billing_documents": frozenset(
        {"billing_document_id", "sales_order_id", "billing_date", "billing_status"}
    ),
}
EXPECTED_BUSINESS_FIELD_CANDIDATES = {
    "delivery_date": "ActualGoodsMovementDate",
    "delivery_status": "OverallGoodsMovementStatus",
    "billing_date": "BillingDocumentDate",
    "billing_status": "AccountingPostingStatus",
}
OUTPUT_DEFINITION_BY_OPERATION = {
    "search_sales_orders": "sales_order_summary",
    "get_sales_order": "sales_order_summary",
    "get_related_deliveries": "delivery_summary",
    "get_related_billing_documents": "billing_document_summary",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OFFICIAL_BASELINE = {
    "product": "SAP S/4HANA",
    "release": "2023",
    "software_component": "S4CORE",
    "component_release": "108",
}


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def codes(self) -> set[str]:
        return {issue.code for issue in self.issues}


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, message=message)


def _schema_issues(model: dict[str, Any], schema: dict[str, Any]) -> Iterable[ValidationIssue]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(model), key=lambda item: list(item.absolute_path)):
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        yield _issue("E_MODEL_SCHEMA", path or "/", error.message)


def _reference_issues(model: dict[str, Any]) -> Iterable[ValidationIssue]:
    entities = model.get("entities", {})
    relationships = model.get("relationships", {})
    operations = model.get("operations", {})
    output_schemas = model.get("output_schemas", {})
    bindings = model.get("bindings", {})
    runtime_services = model.get("runtime_services", {})

    allowed_selectors = {
        "SAP_ODATA_BASE_URL",
        "SAP_DELIVERY_ODATA_BASE_URL",
        "SAP_BILLING_ODATA_BASE_URL",
    }
    for service_id, service in runtime_services.items():
        selector = service.get("runtime_selector") if isinstance(service, dict) else None
        if selector not in allowed_selectors:
            yield _issue(
                "E_RUNTIME_SELECTOR",
                f"/runtime_services/{service_id}/runtime_selector",
                "runtime selector is not an allowlisted SAP OData selector",
            )

    actual_operations = set(operations)
    if actual_operations != CANONICAL_OPERATIONS:
        unknown = sorted(actual_operations - CANONICAL_OPERATIONS)
        missing = sorted(CANONICAL_OPERATIONS - actual_operations)
        if unknown:
            yield _issue("E_UNKNOWN_OPERATION", "/operations", f"not allowlisted: {unknown}")
        if missing:
            yield _issue("E_MISSING_OPERATION", "/operations", f"required operations absent: {missing}")

    for relationship_id, relationship in relationships.items():
        for field in ("source", "target"):
            entity_id = relationship.get(field)
            if entity_id not in entities:
                yield _issue(
                    "E_UNKNOWN_ENTITY",
                    f"/relationships/{relationship_id}/{field}",
                    f"unknown entity {entity_id!r}",
                )
        for operation_id in relationship.get("operations", []):
            if operation_id not in operations:
                yield _issue(
                    "E_UNKNOWN_OPERATION_REF",
                    f"/relationships/{relationship_id}/operations",
                    f"unknown operation {operation_id!r}",
                )

    for operation_id, operation in operations.items():
        for entity_id in operation.get("entity_refs", []):
            if entity_id not in entities:
                yield _issue(
                    "E_UNKNOWN_ENTITY",
                    f"/operations/{operation_id}/entity_refs",
                    f"unknown entity {entity_id!r}",
                )
        for relationship_id in operation.get("relationship_refs", []):
            if relationship_id not in relationships:
                yield _issue(
                    "E_UNKNOWN_RELATIONSHIP",
                    f"/operations/{operation_id}/relationship_refs",
                    f"unknown relationship {relationship_id!r}",
                )
        output_ref = operation.get("output_schema_ref")
        if output_ref not in output_schemas:
            yield _issue(
                "E_UNKNOWN_OUTPUT_SCHEMA",
                f"/operations/{operation_id}/output_schema_ref",
                f"unknown output schema {output_ref!r}",
            )
        binding_ref = operation.get("binding_ref")
        if binding_ref not in bindings:
            yield _issue(
                "E_MISSING_BINDING",
                f"/operations/{operation_id}/binding_ref",
                f"unknown binding {binding_ref!r}",
            )
            continue
        input_properties = operation.get("input_schema", {}).get("properties", {})
        if operation_id == "search_sales_orders":
            input_properties = input_properties.get("criteria", {}).get("properties", {})
        actual_parameters = set(input_properties)
        expected_parameters = EXPECTED_PARAMETERS.get(operation_id, frozenset())
        if actual_parameters != expected_parameters:
            yield _issue(
                "E_PARAMETER_SET",
                f"/operations/{operation_id}/input_schema",
                f"expected {sorted(expected_parameters)}, got {sorted(actual_parameters)}",
            )
        for parameter_id, parameter_schema in input_properties.items():
            if not isinstance(parameter_schema, dict) or not isinstance(
                parameter_schema.get("description"), str
            ) or not parameter_schema["description"].strip():
                parameter_path = (
                    f"/operations/{operation_id}/input_schema/properties/{parameter_id}"
                )
                if operation_id == "search_sales_orders":
                    parameter_path = (
                        f"/operations/{operation_id}/input_schema/properties/criteria/properties/{parameter_id}"
                    )
                yield _issue(
                    "E_PARAMETER_DESCRIPTION",
                    parameter_path,
                    "Agent-visible parameters must have a non-empty business description",
                )
        binding = bindings[binding_ref]
        if binding.get("service_id") not in runtime_services:
            yield _issue(
                "E_UNKNOWN_RUNTIME_SERVICE",
                f"/bindings/{binding_ref}/service_id",
                f"service {binding.get('service_id')!r} is not declared in runtime_services",
            )
        enrichment = binding.get("enrichment")
        if isinstance(enrichment, dict) and enrichment.get("service_id") not in runtime_services:
            yield _issue(
                "E_UNKNOWN_RUNTIME_SERVICE",
                f"/bindings/{binding_ref}/enrichment/service_id",
                f"service {enrichment.get('service_id')!r} is not declared in runtime_services",
            )
        bound_parameters = set(binding.get("parameters", {}))
        if bound_parameters != expected_parameters:
            yield _issue(
                "E_PARAMETER_BINDING_SET",
                f"/bindings/{binding_ref}/parameters",
                f"expected {sorted(expected_parameters)}, got {sorted(bound_parameters)}",
            )
        bound_outputs = set(binding.get("output_fields", {}))
        expected_outputs = EXPECTED_OUTPUT_FIELDS.get(operation_id, frozenset())
        if bound_outputs != expected_outputs:
            yield _issue(
                "E_OUTPUT_BINDING_SET",
                f"/bindings/{binding_ref}/output_fields",
                f"expected {sorted(expected_outputs)}, got {sorted(bound_outputs)}",
            )


def _policy_issues(model: dict[str, Any]) -> Iterable[ValidationIssue]:
    policies = model.get("policies", {})
    if policies.get("allowed_http_methods") != ["GET"]:
        yield _issue(
            "E_READ_ONLY_POLICY",
            "/policies/allowed_http_methods",
            "the only allowed method must be GET",
        )
    if policies.get("allow_unverified_bindings") is not False:
        yield _issue(
            "E_UNVERIFIED_FALLBACK",
            "/policies/allow_unverified_bindings",
            "unverified bindings must be rejected",
        )
    if policies.get("fallback") != "forbidden":
        yield _issue("E_FALLBACK_POLICY", "/policies/fallback", "fallback must be forbidden")

    for operation_id, operation in model.get("operations", {}).items():
        if operation.get("method") != "GET":
            yield _issue(
                "E_NON_GET_OPERATION",
                f"/operations/{operation_id}/method",
                "operation must use GET",
            )
        input_schema = operation.get("input_schema", {})
        if input_schema.get("additionalProperties") is not False:
            yield _issue(
                "E_OPEN_PARAMETER_SCHEMA",
                f"/operations/{operation_id}/input_schema/additionalProperties",
                "unknown parameters must be rejected",
            )


def _business_field_issues(
    model: dict[str, Any], require_compilable: bool
) -> Iterable[ValidationIssue]:
    fields = model.get("business_fields", {})
    actual = set(fields)
    expected = set(EXPECTED_BUSINESS_FIELD_CANDIDATES)
    if actual != expected:
        yield _issue(
            "E_BUSINESS_FIELD_SET",
            "/business_fields",
            f"expected {sorted(expected)}, got {sorted(actual)}",
        )
    for field_id, candidate in EXPECTED_BUSINESS_FIELD_CANDIDATES.items():
        field = fields.get(field_id)
        if isinstance(field, dict) and field.get("candidate_property") != candidate:
            yield _issue(
                "E_BUSINESS_FIELD_CANDIDATE",
                f"/business_fields/{field_id}/candidate_property",
                f"expected tenant-validation candidate {candidate!r}",
            )
        if (
            require_compilable
            and isinstance(field, dict)
            and field.get("binding_status") != "tenant_verified"
        ):
            yield _issue(
                "E_UNVERIFIED_BUSINESS_FIELD",
                f"/business_fields/{field_id}/binding_status",
                "compilation requires tenant-verified business semantics",
            )


def _output_schema_issues(model: dict[str, Any]) -> Iterable[ValidationIssue]:
    forbidden_tokens = ("endpoint", "credential", "entity_set", "odata_query", "raw_row")
    for schema_id, schema in model.get("output_schemas", {}).items():
        serialized = str(schema).lower()
        for token in forbidden_tokens:
            if token in serialized:
                yield _issue(
                    "E_PRIVATE_OUTPUT_FIELD",
                    f"/output_schemas/{schema_id}",
                    f"agent-visible output contains private token {token!r}",
                )
    for operation_id, operation in model.get("operations", {}).items():
        try:
            Draft202012Validator.check_schema(operation.get("input_schema", {}))
        except Exception as exc:  # jsonschema exposes several schema-error subclasses
            yield _issue(
                "E_INVALID_JSON_SCHEMA",
                f"/operations/{operation_id}/input_schema",
                str(exc).splitlines()[0],
            )
    for schema_id, output_schema in model.get("output_schemas", {}).items():
        if schema_id == "$defs":
            continue
        bundled = dict(output_schema)
        bundled["$defs"] = model.get("output_schemas", {}).get("$defs", {})
        try:
            Draft202012Validator.check_schema(bundled)
        except Exception as exc:
            yield _issue(
                "E_INVALID_JSON_SCHEMA",
                f"/output_schemas/{schema_id}",
                str(exc).splitlines()[0],
            )


def _evidence_index(evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("source_evidence_id"): item
        for item in evidence.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("source_evidence_id"), str)
    }


def _official_service_index(official_evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(official_evidence, dict):
        return {}
    return {
        item.get("service_id"): item
        for item in official_evidence.get("services", [])
        if isinstance(item, dict) and isinstance(item.get("service_id"), str)
    }


def _tenant_status_observations(evidence: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Index sanitized representative status observations by SAP property and code."""
    observed: dict[str, dict[str, str]] = {}
    for record in evidence.get("evidence", []):
        if not isinstance(record, dict):
            continue
        for case in record.get("field_validations", []):
            if not isinstance(case, dict):
                continue
            if case.get("query_status") != "passed" or case.get("returned_object") is not True:
                continue
            property_name = {
                "delivery": "OverallGoodsMovementStatus",
                "billing": "AccountingPostingStatus",
            }.get(case.get("service"))
            code = case.get("status_code")
            value = case.get("status_business_value")
            if property_name and isinstance(code, str) and isinstance(value, str):
                observed.setdefault(property_name, {})[code] = value
        for case in record.get("sales_order_status_validations", []):
            if not isinstance(case, dict):
                continue
            if case.get("query_status") != "passed" or case.get("returned_object") is not True:
                continue
            code = case.get("status_code")
            value = case.get("status_business_value")
            if isinstance(code, str) and isinstance(value, str):
                observed.setdefault("OverallSDProcessStatus", {})[code] = value
        observations = record.get("observations", {})
        if not isinstance(observations, dict):
            continue
        for scope, property_name in (
            ("delivery", "OverallGoodsMovementStatus"),
            ("billing", "AccountingPostingStatus"),
        ):
            item = observations.get(scope)
            if not isinstance(item, dict):
                continue
            code = item.get("status_code")
            value = item.get("status_business_value")
            if isinstance(code, str) and isinstance(value, str):
                observed.setdefault(property_name, {})[code] = value
    return observed


def _tenant_status_domain_evidence(
    evidence: dict[str, Any], property_name: str
) -> dict[str, Any] | None:
    for record in evidence.get("evidence", []):
        if not isinstance(record, dict):
            continue
        for item in record.get("status_domain_validations", []):
            if (
                isinstance(item, dict)
                and item.get("property") == property_name
            ):
                return item
    return None


def _multi_source_evidence_issues(
    model: dict[str, Any],
    tenant_evidence: dict[str, Any],
    official_evidence: dict[str, Any] | None,
    require_compilable: bool,
) -> Iterable[ValidationIssue]:
    policy = model.get("evidence_policy", {})
    policy_path = "/evidence_policy"
    if policy.get("validation_mode") != "multi_source":
        yield _issue("E_EVIDENCE_POLICY", policy_path, "validation_mode must be multi_source")
        return
    baseline = {
        key: policy.get(key)
        for key in ("product", "release", "software_component", "component_release")
    }
    if baseline != OFFICIAL_BASELINE:
        yield _issue(
            "E_RELEASE_BASELINE",
            policy_path,
            "model evidence policy must pin SAP S/4HANA 2023 / S4CORE 108",
        )
    if tenant_evidence.get("release_baseline") != OFFICIAL_BASELINE:
        yield _issue(
            "E_TENANT_RELEASE_BASELINE",
            "/evidence/release_baseline",
            "tenant evidence must be reconciled against SAP S/4HANA 2023 / S4CORE 108",
        )
    if not isinstance(official_evidence, dict):
        yield _issue(
            "E_MISSING_OFFICIAL_EVIDENCE",
            "/official_evidence",
            "multi-source validation requires SAP official release evidence",
        )
        return
    if official_evidence.get("classification") != "sap-official-release-evidence":
        yield _issue("E_OFFICIAL_EVIDENCE_SHAPE", "/official_evidence/classification", "unexpected official evidence classification")
    if official_evidence.get("evidence_id") != policy.get("official_release_evidence_id"):
        yield _issue("E_OFFICIAL_EVIDENCE_ID", "/official_evidence/evidence_id", "official evidence does not match the model policy")
    if official_evidence.get("baseline") != OFFICIAL_BASELINE:
        yield _issue(
            "E_RELEASE_BASELINE_MISMATCH",
            "/official_evidence/baseline",
            "official evidence must target SAP S/4HANA 2023 / S4CORE 108",
        )

    services = _official_service_index(official_evidence)
    operation_by_binding = {
        operation.get("binding_ref"): operation_id
        for operation_id, operation in model.get("operations", {}).items()
    }
    tenant_statuses = _tenant_status_observations(tenant_evidence)
    checked_status_domains: set[tuple[str, str]] = set()

    def check_service(
        *, service_id: Any, entity_set: Any, fields: list[dict[str, Any]], operation_id: str | None, path: str
    ) -> Iterable[ValidationIssue]:
        service = services.get(service_id)
        if not isinstance(service, dict) or service.get("evidence_status") != "official_documented":
            yield _issue("E_OFFICIAL_SERVICE_COVERAGE", path, f"service {service_id!r} lacks SAP official API evidence")
            return
        if operation_id and operation_id not in service.get("operations", []):
            yield _issue("E_OFFICIAL_OPERATION_COVERAGE", path, f"operation {operation_id!r} is not covered by the official service definition")
        documented = service.get("entity_sets", {}).get(entity_set, [])
        if not isinstance(documented, list):
            documented = []
        required_properties = {
            field.get("property")
            for field in fields
            if isinstance(field, dict) and isinstance(field.get("property"), str)
        }
        missing = sorted(required_properties - set(documented))
        if missing:
            yield _issue("E_OFFICIAL_PROPERTY_COVERAGE", path, "official API evidence is missing properties: " + ", ".join(missing))

        domains = service.get("status_domains", {})
        for field in fields:
            if not isinstance(field, dict):
                continue
            property_name = field.get("property")
            if not isinstance(property_name, str) or not property_name.endswith("Status"):
                continue
            domain_key = (str(service_id), property_name)
            if domain_key in checked_status_domains:
                continue
            checked_status_domains.add(domain_key)
            domain = domains.get(property_name) if isinstance(domains, dict) else None
            domain_path = f"{path}/status_domains/{property_name}"
            if not isinstance(domain, dict) or domain.get("evidence_status") != "official_documented":
                yield _issue("E_OFFICIAL_STATUS_DOMAIN", domain_path, "status property lacks an SAP official code-list definition")
                continue
            values = domain.get("values")
            if not isinstance(values, dict) or not values:
                yield _issue("E_OFFICIAL_STATUS_DOMAIN", domain_path, "official status domain must contain code values")
                continue
            if property_name == "AccountingPostingStatus" and require_compilable:
                tenant_domain = _tenant_status_domain_evidence(
                    tenant_evidence, property_name
                )
                if not isinstance(tenant_domain, dict) or tenant_domain.get("completeness") != "complete":
                    yield _issue(
                        "E_TENANT_STATUS_DOMAIN",
                        domain_path,
                        "Billing status requires complete tenant DDIC domain evidence",
                    )
                else:
                    tenant_values = tenant_domain.get("values")
                    if not isinstance(tenant_values, dict):
                        yield _issue(
                            "E_TENANT_STATUS_DOMAIN",
                            domain_path,
                            "tenant Billing status domain must contain code values",
                        )
                    elif set(tenant_values) != set(values):
                        yield _issue(
                            "E_TENANT_STATUS_DOMAIN_MISMATCH",
                            domain_path,
                            "tenant Billing DDIC values must equal the official domain",
                        )
                    else:
                        mismatched_tenant = sorted(
                            code
                            for code in values
                            if not isinstance(tenant_values.get(code), dict)
                            or tenant_values[code].get("business_value") != values[code]
                        )
                        if mismatched_tenant:
                            yield _issue(
                                "E_TENANT_STATUS_DOMAIN_MISMATCH",
                                domain_path,
                                "tenant Billing DDIC semantic mappings conflict with the official domain: "
                                + ", ".join(mismatched_tenant),
                            )
            if require_compilable and domain.get("completeness") != "complete":
                yield _issue("E_OFFICIAL_STATUS_DOMAIN_INCOMPLETE", domain_path, "compilation requires a complete official status domain")
            model_map = field.get("code_map")
            if isinstance(model_map, dict):
                unknown = sorted(set(model_map) - set(values))
                mismatched = sorted(code for code in set(model_map) & set(values) if model_map[code] != values[code])
                if unknown or mismatched:
                    yield _issue("E_STATUS_OFFICIAL_MISMATCH", domain_path, "model status mapping conflicts with the SAP official domain")
            declared_observed = field.get("tenant_observed_codes", [])
            if declared_observed and set(declared_observed) != set(tenant_statuses.get(property_name, {})):
                yield _issue("E_STATUS_OBSERVATION_DECLARATION", domain_path, "model tenant_observed_codes do not match sanitized tenant cases")
            if require_compilable:
                observed = tenant_statuses.get(property_name, {})
                if not observed:
                    yield _issue("E_STATUS_REPRESENTATIVE_CASE", domain_path, "at least one tenant-observed representative status is required")
                elif any(code not in values or values[code] != meaning for code, meaning in observed.items()):
                    yield _issue("E_STATUS_REPRESENTATIVE_MISMATCH", domain_path, "tenant-observed status conflicts with the official code list")

    for binding_id, binding in model.get("bindings", {}).items():
        if not isinstance(binding, dict):
            continue
        operation_id = operation_by_binding.get(binding_id)
        base_fields = [
            *binding.get("parameters", {}).values(),
            *(field for field in binding.get("output_fields", {}).values() if field.get("step_ref") != "enrichment"),
        ]
        discriminator = binding.get("discriminator")
        if isinstance(discriminator, dict):
            base_fields.append(discriminator)
        yield from check_service(
            service_id=binding.get("service_id"),
            entity_set=binding.get("entity_set"),
            fields=base_fields,
            operation_id=operation_id,
            path=f"/bindings/{binding_id}",
        )
        enrichment = binding.get("enrichment")
        if isinstance(enrichment, dict):
            enrichment_fields = [
                {"property": enrichment.get("key_property")},
                *(field for field in binding.get("output_fields", {}).values() if field.get("step_ref") == "enrichment"),
            ]
            yield from check_service(
                service_id=enrichment.get("service_id"),
                entity_set=enrichment.get("entity_set"),
                fields=enrichment_fields,
                operation_id=operation_id,
                path=f"/bindings/{binding_id}/enrichment",
            )


def _scoped_properties(item: dict[str, Any] | None, scope: str | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Return sanitized metadata properties for a service scope in an evidence record."""
    if not isinstance(item, dict):
        return {}, None
    source: Any = item
    if scope:
        observations = item.get("observations")
        if isinstance(observations, dict) and isinstance(observations.get(scope), dict):
            source = observations[scope]
        else:
            service_metadata = item.get("service_metadata")
            if isinstance(service_metadata, dict) and isinstance(service_metadata.get(scope), dict):
                source = service_metadata[scope]
            else:
                return {}, None
    properties = source.get("properties") if isinstance(source, dict) else None
    if not isinstance(properties, list):
        return {}, source.get("metadata_sha256") if isinstance(source, dict) else None
    return {
        property_item.get("name"): property_item
        for property_item in properties
        if isinstance(property_item, dict) and isinstance(property_item.get("name"), str)
    }, source.get("metadata_sha256") if isinstance(source, dict) else None


def _binding_metadata_properties(
    item: dict[str, Any] | None, entity_set: str | None
) -> dict[str, dict[str, Any]]:
    """Return the tenant metadata properties for one concrete binding EntitySet."""
    if not isinstance(item, dict) or not isinstance(entity_set, str):
        return {}
    observations = item.get("observations")
    if not isinstance(observations, dict):
        return {}
    source: dict[str, Any] | None = None
    if observations.get("selected_entity_set") == entity_set:
        source = observations
    else:
        for option in observations.get("document_flow_options", []):
            if isinstance(option, dict) and option.get("entitySet") == entity_set:
                source = option
                break
    properties = source.get("properties") if isinstance(source, dict) else None
    if not isinstance(properties, list):
        return {}
    return {
        prop.get("name"): prop
        for prop in properties
        if isinstance(prop, dict) and isinstance(prop.get("name"), str)
    }


def _verified_category_values(item: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for case in item.get("case_validations", []):
        if not isinstance(case, dict):
            continue
        for mapping in case.get("category_mappings", []):
            if isinstance(mapping, dict) and isinstance(mapping.get("business_value"), str):
                values.add(mapping["business_value"])
    return values


def _has_representative_enrichment_case(item: dict[str, Any], scope: str | None) -> bool:
    if scope not in {"delivery", "billing"}:
        return False
    for case in item.get("field_validations", []):
        if (
            isinstance(case, dict)
            and case.get("service") == scope
            and case.get("query_status") == "passed"
            and case.get("returned_object") is True
        ):
            return True
    observations = item.get("observations", {})
    scoped = observations.get(scope) if isinstance(observations, dict) else None
    return bool(
        isinstance(scoped, dict)
        and scoped.get("query_status") == "passed"
        and scoped.get("returned_object") is True
    )


def _binding_issues(
    model: dict[str, Any], evidence: dict[str, Any], require_compilable: bool
) -> Iterable[ValidationIssue]:
    evidence_by_id = _evidence_index(evidence)
    model_info = model.get("model", {})
    operations = model.get("operations", {})
    operation_by_binding = {
        operation.get("binding_ref"): (operation_id, operation)
        for operation_id, operation in operations.items()
    }
    for binding_id, binding in model.get("bindings", {}).items():
        path = f"/bindings/{binding_id}"
        operation_id, _operation = operation_by_binding.get(binding_id, (None, {}))
        if binding.get("method") != "GET":
            yield _issue("E_NON_GET_BINDING", f"{path}/method", "binding must use GET")
        evidence_id = binding.get("source_evidence_id")
        item = evidence_by_id.get(evidence_id)
        if item is None:
            yield _issue(
                "E_MISSING_EVIDENCE",
                f"{path}/source_evidence_id",
                f"evidence {evidence_id!r} was not supplied",
            )
            continue
        if item.get("source_id") != model_info.get("source_id"):
            yield _issue("E_SOURCE_MISMATCH", path, "binding evidence uses a different source_id")
        if item.get("protocol") != "odata-v2" or item.get("odata_version") != "2.0":
            yield _issue("E_PROTOCOL_MISMATCH", path, "binding evidence is not OData V2")

        if require_compilable:
            if binding.get("status") != "tenant_verified" or item.get("status") != "tenant_verified":
                yield _issue(
                    "E_UNVERIFIED_BINDING",
                    path,
                    "compilable models require tenant_verified binding and evidence",
                )
            metadata_hash = item.get("metadata_sha256")
            if not isinstance(metadata_hash, str) or not SHA256_RE.fullmatch(metadata_hash):
                yield _issue(
                    "E_METADATA_HASH",
                    f"{path}/source_evidence_id",
                    "tenant evidence requires a complete lowercase SHA-256",
                )
            if binding.get("metadata_sha256") != metadata_hash:
                yield _issue(
                    "E_METADATA_HASH_MISMATCH",
                    f"{path}/metadata_sha256",
                    "binding does not pin the supplied evidence metadata hash",
                )
            if binding_id not in item.get("verified_bindings", []):
                yield _issue(
                    "E_BINDING_NOT_IN_EVIDENCE",
                    path,
                    "sanitized evidence does not list this binding as verified",
                )
            smoke_tests = item.get("smoke_tests", {})
            if binding_id in {"search_sales_orders_binding", "get_sales_order_binding"}:
                required_smokes = {"metadata_get", "sales_order_collection_get", "sales_order_filter"}
                if not isinstance(smoke_tests, dict) or any(smoke_tests.get(name) != "passed" for name in required_smokes):
                    yield _issue(
                        "E_BINDING_SMOKE_EVIDENCE",
                        path,
                        "Sales Order binding requires metadata, collection GET and filter smoke evidence",
                    )
            if operation_id in {"get_related_deliveries", "get_related_billing_documents"}:
                expected_category = "outbound_delivery" if operation_id == "get_related_deliveries" else "billing_document"
                if expected_category not in _verified_category_values(item):
                    yield _issue(
                        "E_DISCRIMINATOR_CASE_EVIDENCE",
                        f"{path}/discriminator",
                        f"tenant known cases do not confirm {expected_category}",
                    )
            if not binding.get("entity_set"):
                yield _issue("E_ENTITY_SET_BINDING", path, "entity_set is required for compilation")
            if operation_id in {
                "get_related_deliveries",
                "get_related_billing_documents",
            }:
                enrichment = binding.get("enrichment")
                if not isinstance(enrichment, dict):
                    yield _issue(
                        "E_MISSING_ENRICHMENT",
                        f"{path}/enrichment",
                        "related-document binding requires a document-service enrichment step",
                    )
                else:
                    enrichment_path = f"{path}/enrichment"
                    enrichment_id = enrichment.get("source_evidence_id")
                    enrichment_item = evidence_by_id.get(enrichment_id)
                    if enrichment.get("method") != "GET":
                        yield _issue("E_NON_GET_ENRICHMENT", f"{enrichment_path}/method", "enrichment must use GET")
                    if enrichment.get("query_strategy") != "unique_filter":
                        yield _issue(
                            "E_ENRICHMENT_QUERY_STRATEGY",
                            f"{enrichment_path}/query_strategy",
                            "enrichment must resolve one document by key",
                        )
                    if not enrichment.get("service_id") or not enrichment.get("entity_set"):
                        yield _issue(
                            "E_ENRICHMENT_SERVICE_BINDING",
                            enrichment_path,
                            "enrichment service_id and entity_set are required",
                        )
                    if not enrichment.get("key_property") or not enrichment.get("input_field"):
                        yield _issue(
                            "E_ENRICHMENT_KEY_BINDING",
                            enrichment_path,
                            "enrichment key_property and input_field are required",
                        )
                    if enrichment.get("evidence_scope") not in {"delivery", "billing"}:
                        yield _issue(
                            "E_ENRICHMENT_SCOPE",
                            f"{enrichment_path}/evidence_scope",
                            "enrichment evidence_scope must be delivery or billing",
                        )
                    if enrichment_item is None:
                        yield _issue(
                            "E_ENRICHMENT_EVIDENCE",
                            f"{enrichment_path}/source_evidence_id",
                            f"evidence {enrichment_id!r} was not supplied",
                        )
                    else:
                        if enrichment_item.get("source_id") != model_info.get("source_id"):
                            yield _issue("E_SOURCE_MISMATCH", enrichment_path, "enrichment evidence uses a different source_id")
                        if enrichment_item.get("protocol") != "odata-v2" or enrichment_item.get("odata_version") != "2.0":
                            yield _issue("E_PROTOCOL_MISMATCH", enrichment_path, "enrichment evidence is not OData V2")
                        if enrichment.get("status") != "tenant_verified" or enrichment_item.get("status") != "tenant_verified":
                            yield _issue(
                                "E_UNVERIFIED_ENRICHMENT",
                                enrichment_path,
                                "compilable models require tenant_verified enrichment and evidence",
                            )
                        enrichment_hash = enrichment_item.get("metadata_sha256")
                        if not isinstance(enrichment_hash, str) or not SHA256_RE.fullmatch(enrichment_hash):
                            yield _issue("E_ENRICHMENT_METADATA", f"{enrichment_path}/metadata_sha256", "enrichment evidence requires a complete lowercase SHA-256")
                        token = f"{binding_id}:enrichment"
                        if token not in enrichment_item.get("verified_bindings", []):
                            yield _issue("E_ENRICHMENT_NOT_IN_EVIDENCE", enrichment_path, "sanitized evidence does not list this enrichment as verified")
                        if not _has_representative_enrichment_case(
                            enrichment_item, enrichment.get("evidence_scope")
                        ):
                            yield _issue(
                                "E_ENRICHMENT_CASE_EVIDENCE",
                                enrichment_path,
                                "enrichment requires a successful representative tenant document case",
                            )
                        scoped_properties, scoped_hash = _scoped_properties(enrichment_item, enrichment.get("evidence_scope"))
                        effective_hash = scoped_hash or enrichment_hash
                        if not isinstance(effective_hash, str) or not SHA256_RE.fullmatch(effective_hash):
                            yield _issue("E_ENRICHMENT_METADATA", f"{enrichment_path}/metadata_sha256", "scoped enrichment metadata requires a complete lowercase SHA-256")
                        if enrichment.get("metadata_sha256") != effective_hash:
                            yield _issue("E_ENRICHMENT_METADATA_MISMATCH", f"{enrichment_path}/metadata_sha256", "enrichment does not pin its scoped evidence metadata hash")
                        required_names = {enrichment.get("key_property")}
                        for field_binding in binding.get("output_fields", {}).values():
                            if field_binding.get("step_ref") == "enrichment" and field_binding.get("property"):
                                required_names.add(field_binding["property"])
                        missing = sorted(name for name in required_names if name not in scoped_properties)
                        if missing:
                            yield _issue(
                                "E_ENRICHMENT_PROPERTY",
                                enrichment_path,
                                "enrichment evidence is missing properties: " + ", ".join(missing),
                            )
                discriminator = binding.get("discriminator")
                if not isinstance(discriminator, dict):
                    yield _issue(
                        "E_MISSING_DISCRIMINATOR",
                        f"{path}/discriminator",
                        "related-document binding requires a category discriminator",
                    )
                else:
                    if (
                        discriminator.get("status") != "tenant_verified"
                        or not discriminator.get("property")
                        or not discriminator.get("code_map")
                    ):
                        yield _issue(
                            "E_UNVERIFIED_DISCRIMINATOR",
                            f"{path}/discriminator",
                            "category property and code map must be tenant_verified",
                        )
                    business_value = discriminator.get("business_value")
                    if business_value not in set((discriminator.get("code_map") or {}).values()):
                        yield _issue(
                            "E_DISCRIMINATOR_CODE_MAP",
                            f"{path}/discriminator",
                            "code map must contain the declared business category",
                        )
                    metadata_properties = _binding_metadata_properties(
                        item, binding.get("entity_set")
                    )
                    property_name = discriminator.get("property")
                    metadata_property = metadata_properties.get(property_name)
                    if metadata_property is None:
                        yield _issue(
                            "E_TENANT_DISCRIMINATOR_PROPERTY",
                            f"{path}/discriminator",
                            "discriminator is not present in the binding EntitySet tenant metadata",
                        )
                    else:
                        if metadata_property.get("edm_type") != discriminator.get("edm_type"):
                            yield _issue(
                                "E_TENANT_DISCRIMINATOR_TYPE",
                                f"{path}/discriminator",
                                "discriminator EDM type does not match tenant metadata",
                            )
                        if (
                            discriminator.get("edm_type") == "Edm.String"
                            and metadata_property.get("max_length")
                            != discriminator.get("max_length")
                        ):
                            yield _issue(
                                "E_TENANT_DISCRIMINATOR_LENGTH",
                                f"{path}/discriminator",
                                "discriminator MaxLength does not match tenant metadata",
                            )
            for section in ("parameters", "output_fields"):
                for field_id, field_binding in binding.get(section, {}).items():
                    field_path = f"{path}/{section}/{field_id}"
                    if field_binding.get("status") != "tenant_verified":
                        yield _issue(
                            "E_UNVERIFIED_FIELD_BINDING",
                            field_path,
                            "field mapping is not tenant_verified",
                        )
                    if not field_binding.get("property"):
                        yield _issue(
                            "E_MISSING_PROPERTY_BINDING",
                            field_path,
                            "SAP property is required for compilation",
                        )
                    edm_type = field_binding.get("edm_type")
                    if not isinstance(edm_type, str) or not edm_type.startswith("Edm."):
                        yield _issue(
                            "E_MISSING_EDM_TYPE",
                            field_path,
                            "tenant-verified field requires an EDM type",
                        )
                    if edm_type == "Edm.String" and not isinstance(field_binding.get("max_length"), int):
                        yield _issue(
                            "E_MISSING_MAX_LENGTH",
                            field_path,
                            "tenant-verified string field requires metadata MaxLength",
                        )
                    if section == "parameters" and edm_type == "Edm.String" and not field_id.endswith("status"):
                        operation_id, operation = operation_by_binding.get(binding_id, (None, {}))
                        properties = operation.get("input_schema", {}).get("properties", {})
                        if operation_id == "search_sales_orders":
                            properties = properties.get("criteria", {}).get("properties", {})
                        parameter_schema = properties.get(field_id, {})
                        if parameter_schema.get("maxLength") != field_binding.get("max_length"):
                            yield _issue(
                                "E_PARAMETER_LENGTH_MISMATCH",
                                field_path,
                                "input maxLength must equal tenant metadata MaxLength",
                            )
                    if field_binding.get("step_ref") == "enrichment":
                        enrichment = binding.get("enrichment")
                        enrichment_item = evidence_by_id.get((enrichment or {}).get("source_evidence_id"))
                        scoped_properties, _ = _scoped_properties(
                            enrichment_item, (enrichment or {}).get("evidence_scope")
                        )
                        property_name = field_binding.get("property")
                        metadata_property = scoped_properties.get(property_name)
                        if metadata_property is None:
                            yield _issue(
                                "E_ENRICHMENT_FIELD_PROPERTY",
                                field_path,
                                "enrichment field is not present in scoped tenant metadata",
                            )
                        else:
                            if metadata_property.get("edm_type") != edm_type:
                                yield _issue(
                                    "E_ENRICHMENT_FIELD_TYPE",
                                    field_path,
                                    "enrichment field EDM type does not match tenant metadata",
                                )
                            if edm_type == "Edm.String" and metadata_property.get("max_length") != field_binding.get("max_length"):
                                yield _issue(
                                    "E_ENRICHMENT_FIELD_LENGTH",
                                    field_path,
                                    "enrichment string field MaxLength does not match tenant metadata",
                                )
                    else:
                        metadata_properties = _binding_metadata_properties(
                            item, binding.get("entity_set")
                        )
                        property_name = field_binding.get("property")
                        metadata_property = metadata_properties.get(property_name)
                        if metadata_property is None:
                            yield _issue(
                                "E_TENANT_FIELD_PROPERTY",
                                field_path,
                                "field is not present in the binding EntitySet tenant metadata",
                            )
                        else:
                            if metadata_property.get("edm_type") != edm_type:
                                yield _issue(
                                    "E_TENANT_FIELD_TYPE",
                                    field_path,
                                    "field EDM type does not match tenant metadata",
                                )
                            if edm_type == "Edm.String" and metadata_property.get("max_length") != field_binding.get("max_length"):
                                yield _issue(
                                    "E_TENANT_FIELD_LENGTH",
                                    field_path,
                                    "field MaxLength does not match tenant metadata",
                                )
                    if field_id.endswith("status") and not field_binding.get("code_map"):
                        yield _issue(
                            "E_MISSING_STATUS_CODE_MAP",
                            field_path,
                            "status field requires a governed SAP-code mapping",
                        )
                    if section == "parameters" and field_id.endswith("status"):
                        operation_id, operation = operation_by_binding.get(binding_id, (None, {}))
                        properties = operation.get("input_schema", {}).get("properties", {})
                        if operation_id == "search_sales_orders":
                            properties = properties.get("criteria", {}).get("properties", {})
                        allowed_values = set(properties.get(field_id, {}).get("enum", []))
                        governed_values = set((field_binding.get("code_map") or {}).values())
                        if allowed_values != governed_values:
                            yield _issue(
                                "E_STATUS_ENUM_MISMATCH",
                                field_path,
                                "input enum must equal governed business status values",
                            )
                    if section == "output_fields" and field_id.endswith("status"):
                        operation_id, _operation = operation_by_binding.get(binding_id, (None, {}))
                        definition_id = OUTPUT_DEFINITION_BY_OPERATION.get(operation_id)
                        definitions = model.get("output_schemas", {}).get("$defs", {})
                        output_field_schema = (
                            definitions.get(definition_id, {}).get("properties", {}).get(field_id, {})
                        )
                        allowed_values = set(output_field_schema.get("enum", []))
                        governed_values = set((field_binding.get("code_map") or {}).values()) | {None}
                        if allowed_values != governed_values:
                            yield _issue(
                                "E_OUTPUT_STATUS_ENUM_MISMATCH",
                                field_path,
                                "output enum must equal governed business status values plus null",
                            )

    if require_compilable and model_info.get("status") != "validated":
        yield _issue(
            "E_MODEL_NOT_VALIDATED",
            "/model/status",
            "only a validated model may enter compilation",
        )


def validate_model(
    model: dict[str, Any],
    evidence: dict[str, Any],
    schema: dict[str, Any],
    *,
    official_evidence: dict[str, Any] | None = None,
    require_compilable: bool = True,
) -> ValidationResult:
    issues = list(_schema_issues(model, schema))
    issues.extend(_reference_issues(model))
    issues.extend(_policy_issues(model))
    issues.extend(
        _multi_source_evidence_issues(
            model,
            evidence,
            official_evidence,
            require_compilable,
        )
    )
    issues.extend(_business_field_issues(model, require_compilable))
    issues.extend(_output_schema_issues(model))
    issues.extend(_binding_issues(model, evidence, require_compilable))
    issues.sort(key=lambda issue: (issue.path, issue.code, issue.message))
    return ValidationResult(tuple(issues))


def validate_arguments(operation: dict[str, Any], arguments: Any) -> ValidationResult:
    issues: list[ValidationIssue] = []
    validator = Draft202012Validator(operation["input_schema"], format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(arguments), key=lambda item: list(item.absolute_path)):
        path = "/arguments/" + "/".join(str(part) for part in error.absolute_path)
        issues.append(_issue("E_ARGUMENT_SCHEMA", path.rstrip("/"), error.message))

    if isinstance(arguments, dict) and isinstance(arguments.get("criteria"), dict):
        criteria = arguments["criteria"]
        present = [value for value in criteria.values() if value not in (None, "")]
        if not present:
            issues.append(
                _issue(
                    "E_EMPTY_SEARCH_CRITERIA",
                    "/arguments/criteria",
                    "at least one non-empty search criterion is required",
                )
            )
        start = criteria.get("order_date_from")
        end = criteria.get("order_date_to")
        if isinstance(start, str) and isinstance(end, str):
            try:
                if date.fromisoformat(start) > date.fromisoformat(end):
                    issues.append(
                        _issue(
                            "E_INVALID_DATE_RANGE",
                            "/arguments/criteria",
                            "order_date_from must not be later than order_date_to",
                        )
                    )
            except ValueError:
                pass
    return ValidationResult(tuple(issues))
