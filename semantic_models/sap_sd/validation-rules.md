# SAP SD Semantic Model validation rules

This file is the human-readable rule index. The executable authority is
`src/semantic_model/validator.py` together with `model.schema.json`.

| Rule | Build-time requirement |
| --- | --- |
| `E_MODEL_SCHEMA` | The document must satisfy the governed JSON Schema. |
| `E_EVIDENCE_POLICY` / `E_RELEASE_BASELINE*` | Model, SAP official evidence and tenant evidence must all pin SAP S/4HANA 2023 / S4CORE 108. |
| `E_MISSING_OFFICIAL_EVIDENCE` / `E_OFFICIAL_*` | Every compiled service, operation, property and status domain must be covered by the pinned SAP official definition; strict compilation requires complete status domains. |
| `E_UNKNOWN_OPERATION` / `E_MISSING_OPERATION` | The operation set must equal the four canonical Phase 02 operations. |
| `E_UNKNOWN_*` | Entity, relationship, output-schema and operation references must resolve. |
| `E_NON_GET_OPERATION` / `E_NON_GET_BINDING` | Public operations and private bindings must use `GET`. |
| `E_OPEN_PARAMETER_SCHEMA` | Every operation rejects undeclared arguments. |
| `E_PRIVATE_OUTPUT_FIELD` | Agent-visible schemas cannot expose endpoint, credential, EntitySet, query or raw-row details. |
| `E_INVALID_JSON_SCHEMA` | Input and bundled output JSON Schemas must be valid Draft 2020-12 schemas. |
| `E_BUSINESS_FIELD_SET` | The governed business-field set is exactly delivery date/status and billing date/status. |
| `E_BUSINESS_FIELD_CANDIDATE` | Each business field retains its reviewed tenant-validation candidate property. |
| `E_UNVERIFIED_BUSINESS_FIELD` | Compilation requires tenant-verified business semantics for all four fields. |
| `E_MISSING_EVIDENCE` | Every binding references supplied sanitized evidence. |
| `E_SOURCE_MISMATCH` / `E_PROTOCOL_MISMATCH` | Evidence must describe `webmcp.sap_sd.odata` over OData V2. |
| `E_UNVERIFIED_BINDING` | Compilation requires both binding and evidence status `tenant_verified`. |
| `E_METADATA_HASH` | Compilable evidence contains the full lowercase metadata SHA-256. |
| `E_BINDING_SMOKE_EVIDENCE` | Sales Order binding requires passed metadata, collection GET and filter smoke evidence. |
| `E_UNVERIFIED_FIELD_BINDING` | Every compiled input and output field is tenant-verified. |
| `E_MISSING_PROPERTY_BINDING` | Every compiled field maps to an evidenced SAP property. |
| `E_TENANT_FIELD_*` | Property, EDM type and `MaxLength` must equal the binding EntitySet in tenant metadata. |
| `E_MISSING_DISCRIMINATOR` / `E_UNVERIFIED_DISCRIMINATOR` | Related-document bindings require an evidenced category property and code map. |
| `E_DISCRIMINATOR_CASE_EVIDENCE` / `E_TENANT_DISCRIMINATOR_*` | Each related-document business category needs a tenant known case and its discriminator must match tenant metadata. |
| `E_MISSING_ENRICHMENT` / `E_ENRICHMENT_*` | Delivery/Billing composite enrichment needs a successful representative tenant case and exact scoped metadata. |
| `E_STATUS_REPRESENTATIVE_*` | A status domain needs at least one tenant-observed representative value, but not every officially documented code must occur in the tenant cases. |
| Scope boundary | The model covers only Sales Order, Outbound Delivery, Billing Document and document-flow fields; it is not a general SAP SD ontology. |
| Code-list governance | Code lists are required only for status, enumeration, category and discriminator fields; IDs, dates, quantities and customer fields use type/length validation only. |
| `E_PARAMETER_LENGTH_MISMATCH` | Identifier input length must match tenant metadata `MaxLength`. |
| `E_STATUS_ENUM_MISMATCH` / `E_OUTPUT_STATUS_ENUM_MISMATCH` | Input and output business enums must match the governed SAP-code map. |
| `E_MODEL_NOT_VALIDATED` | Only a model whose lifecycle status is `validated` may compile. |
| `E_ARGUMENT_SCHEMA` | Runtime canonical arguments satisfy their closed JSON Schema. |
| `E_EMPTY_SEARCH_CRITERIA` | Search includes at least one non-empty criterion. |
| `E_INVALID_DATE_RANGE` | `order_date_from` is not later than `order_date_to`. |

Draft validation checks the multi-source evidence graph without pretending remaining
evidence gaps are compilation-ready. The Phase 04 compiler must call the strict gate
with both `--evidence` and `--official-evidence` after all five evidence layers close.
