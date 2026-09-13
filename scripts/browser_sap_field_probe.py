"""Serve a browser-direct SAP OData V2 Delivery/Billing field probe.

The browser performs all SAP requests. The local server supplies configuration
and accepts only sanitized metadata/field confirmations; it is not a proxy.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Final
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
DEFAULT_HOST: Final = "localhost"
DEFAULT_PORT: Final = 5173
PROBE_VERSION: Final = "1.1"
MAX_EVIDENCE_BYTES: Final = 1_000_000
SERVICE_DEFINITIONS: Final = {
    "delivery": {
        "env": "SAP_DELIVERY_ODATA_BASE_URL",
        "service": "API_OUTBOUND_DELIVERY_SRV",
        "entity_set": "A_OutbDeliveryHeader",
        "key": "DeliveryDocument",
        "fields": ("DeliveryDocument", "ActualGoodsMovementDate", "OverallGoodsMovementStatus"),
    },
    "billing": {
        "env": "SAP_BILLING_ODATA_BASE_URL",
        "service": "API_BILLING_DOCUMENT_SRV",
        "entity_set": "A_BillingDocument",
        "key": "BillingDocument",
        "fields": ("BillingDocument", "BillingDocumentDate", "AccountingPostingStatus"),
    },
}
ALLOWED_KEYS: Final = {
    "SAP_USER",
    "SAP_PASSWORD",
    "SAP_CLIENT",
    "SAP_LANGUAGE",
    "SAP_DELIVERY_ODATA_BASE_URL",
    "SAP_BILLING_ODATA_BASE_URL",
}
SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
STATUS_BUSINESS_VALUES: Final = {
    "delivery": {"not_started", "partially_completed", "completed", "other"},
    "billing": {"not_relevant", "not_processed", "partially_processed", "completely_processed"},
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise RuntimeError(".env file is missing")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS or key in values:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def service_root(value: str, service_name: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("service selector must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("service selector must not contain credentials, query, or fragment")
    if not parsed.path.rstrip("/").upper().endswith("/" + service_name.upper()) and not parsed.path.rstrip("/").upper().endswith("/" + service_name.upper() + ";V=2"):
        raise RuntimeError(f"service selector must end with {service_name} or {service_name};v=2")
    return candidate + "/"


def public_configuration(env_path: Path) -> dict[str, str]:
    values = load_env(env_path)
    required = ["SAP_USER", "SAP_PASSWORD"] + [definition["env"] for definition in SERVICE_DEFINITIONS.values()]
    missing = [key for key in required if not values.get(key, "").strip()]
    if missing:
        raise RuntimeError("missing required .env keys: " + ", ".join(missing))
    return {
        "username": values["SAP_USER"],
        "password": values["SAP_PASSWORD"],
        "client": values.get("SAP_CLIENT", ""),
        "language": values.get("SAP_LANGUAGE", ""),
        "deliveryServiceUrl": service_root(values["SAP_DELIVERY_ODATA_BASE_URL"], SERVICE_DEFINITIONS["delivery"]["service"]),
        "billingServiceUrl": service_root(values["SAP_BILLING_ODATA_BASE_URL"], SERVICE_DEFINITIONS["billing"]["service"]),
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def metadata_summary(text: str, expected_entity_set: str, required_fields: tuple[str, ...]) -> dict[str, Any]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError("metadata XML parse failed") from exc
    data_services = next((node for node in root.iter() if _local_name(node.tag) == "DataServices"), None)
    version = "unknown"
    if data_services is not None:
        version = next((value for key, value in data_services.attrib.items() if _local_name(key) == "DataServiceVersion"), "unknown")
    if version != "2.0":
        raise ValueError("metadata is not OData V2")
    entity_sets = [node for node in root.iter() if _local_name(node.tag) == "EntitySet"]
    selected = next((node for node in entity_sets if node.attrib.get("Name") == expected_entity_set), None)
    if selected is None:
        raise ValueError(f"metadata does not expose {expected_entity_set}")
    type_name = selected.attrib.get("EntityType", "").split(".")[-1]
    entity_type = next((node for node in root.iter() if _local_name(node.tag) == "EntityType" and node.attrib.get("Name") == type_name), None)
    if entity_type is None:
        raise ValueError(f"metadata does not expose entity type for {expected_entity_set}")
    properties = []
    for node in entity_type:
        if _local_name(node.tag) != "Property":
            continue
        properties.append({
            "name": node.attrib.get("Name", ""),
            "edm_type": node.attrib.get("Type"),
            "max_length": int(node.attrib["MaxLength"]) if node.attrib.get("MaxLength", "").isdigit() else None,
        })
    names = {item["name"] for item in properties}
    missing = [field for field in required_fields if field not in names]
    if missing:
        raise ValueError(f"metadata is missing required properties: {', '.join(missing)}")
    return {
        "version": version,
        "entity_set": expected_entity_set,
        "entity_type": type_name,
        "entity_set_count": len(entity_sets),
        "properties": properties,
    }


def v2_object(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("response is not JSON") from exc
    data = payload.get("d") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or isinstance(data.get("results"), list):
        raise ValueError("response is not an OData V2 single object")
    return data


def _inspect_forbidden(value: object) -> None:
    forbidden = {
        "authorization", "business_key", "business_keys", "credential", "credentials",
        "document_id", "endpoint", "password", "raw_metadata", "raw_row", "raw_rows",
        "service_url", "username",
    }
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise ValueError(f"evidence contains forbidden key: {key}")
            _inspect_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _inspect_forbidden(child)
    elif isinstance(value, str) and ("https://" in value.lower() or "http://" in value.lower()):
        raise ValueError("evidence contains forbidden endpoint material")


def _validate_service_metadata(service_metadata: object) -> None:
    if not isinstance(service_metadata, dict) or set(service_metadata) != set(SERVICE_DEFINITIONS):
        raise ValueError("delivery and billing service metadata are required")
    for kind, metadata in service_metadata.items():
        definition = SERVICE_DEFINITIONS[kind]
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid {kind} service metadata")
        if metadata.get("entity_set") != definition["entity_set"] or not metadata.get("entity_type"):
            raise ValueError(f"unexpected {kind} entity metadata")
        if not isinstance(metadata.get("metadata_sha256"), str) or not SHA256_RE.fullmatch(metadata["metadata_sha256"]):
            raise ValueError(f"complete {kind} metadata SHA-256 is required")
        properties = metadata.get("properties")
        if not isinstance(properties, list) or not properties:
            raise ValueError(f"{kind} metadata properties are required")
        property_names: set[str] = set()
        for item in properties:
            if not isinstance(item, dict) or set(item) != {"name", "edm_type", "max_length"}:
                raise ValueError(f"invalid {kind} metadata property")
            name = item.get("name")
            edm_type = item.get("edm_type")
            max_length = item.get("max_length")
            if not isinstance(name, str) or not isinstance(edm_type, str) or not edm_type.startswith("Edm."):
                raise ValueError(f"invalid {kind} metadata property type")
            if max_length is not None and (not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1):
                raise ValueError(f"invalid {kind} metadata MaxLength")
            property_names.add(name)
        missing = set(definition["fields"]) - property_names
        if missing:
            raise ValueError(f"{kind} metadata is missing required properties")


def _validate_field_validations(field_validations: object) -> None:
    if not isinstance(field_validations, list) or not 1 <= len(field_validations) <= 16:
        raise ValueError("one to sixteen field validations are required")
    mappings: dict[tuple[str, str], str] = {}
    allowed_keys = {
        "case_kind", "service", "query_status", "returned_object", "date_present",
        "status_code", "status_business_value", "semantic_confirmation",
    }
    confirmation_keys = {"method", "confirmed_by_role", "confirmed_at"}
    for case in field_validations:
        if not isinstance(case, dict) or set(case) != allowed_keys:
            raise ValueError("field validation contains unknown or missing fields")
        kind = case.get("service")
        business_value = case.get("status_business_value")
        status_code = case.get("status_code")
        if kind not in STATUS_BUSINESS_VALUES or business_value not in STATUS_BUSINESS_VALUES[kind]:
            raise ValueError("field validation has an unsupported business status")
        if case.get("case_kind") != f"{kind}_{business_value}":
            raise ValueError("field validation case_kind does not match its status")
        if case.get("query_status") != "passed" or case.get("returned_object") is not True:
            raise ValueError(f"{kind} query was not a successful object read")
        if not isinstance(case.get("date_present"), bool):
            raise ValueError(f"{kind} date-present flag is required")
        if not isinstance(status_code, str) or not 1 <= len(status_code) <= 4:
            raise ValueError(f"{kind} status code is required")
        confirmation = case.get("semantic_confirmation")
        if not isinstance(confirmation, dict) or set(confirmation) != confirmation_keys:
            raise ValueError(f"{kind} semantic confirmation is required")
        if confirmation.get("method") != "known_document_cross_check" or confirmation.get("confirmed_by_role") != "researcher_with_sap_ui" or not confirmation.get("confirmed_at"):
            raise ValueError(f"{kind} semantic confirmation is invalid")
        mapping_key = (kind, status_code)
        previous = mappings.get(mapping_key)
        if previous is not None and previous != business_value:
            raise ValueError(f"conflicting {kind} mapping for status code {status_code}")
        mappings[mapping_key] = business_value


def _legacy_field_validations(record: dict[str, Any]) -> list[dict[str, Any]]:
    observations = record.get("observations")
    if not isinstance(observations, dict):
        return []
    validations: list[dict[str, Any]] = []
    for kind in ("delivery", "billing"):
        observation = observations.get(kind)
        if not isinstance(observation, dict) or observation.get("semantic_confirmation") is not True:
            continue
        business_value = observation.get("status_business_value")
        date_key = "actual_goods_movement_date_present" if kind == "delivery" else "billing_document_date_present"
        validations.append({
            "case_kind": f"{kind}_{business_value}",
            "service": kind,
            "query_status": observation.get("query_status"),
            "returned_object": observation.get("returned_object"),
            "date_present": observation.get(date_key) is True,
            "status_code": observation.get("status_code"),
            "status_business_value": business_value,
            "semantic_confirmation": {
                "method": "known_document_cross_check",
                "confirmed_by_role": "researcher_with_sap_ui",
                "confirmed_at": record.get("verified_at"),
            },
        })
    return validations


def field_validations_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    validations = record.get("field_validations")
    return validations if isinstance(validations, list) else _legacy_field_validations(record)


def validate_sanitized_field_evidence(payload: object) -> None:
    if not isinstance(payload, dict) or payload.get("evidence_version") != "2.0" or payload.get("classification") != "sanitized-field-evidence":
        raise ValueError("invalid field evidence envelope")
    records = payload.get("evidence")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError("exactly one field evidence record is required")
    record = records[0]
    if record.get("source_id") != "webmcp.sap_sd.odata" or record.get("protocol") != "odata-v2" or record.get("odata_version") != "2.0":
        raise ValueError("unexpected source or protocol")
    if not str(record.get("source_evidence_id", "")).startswith("sap-odata-v2-fields-"):
        raise ValueError("field evidence must use a field evidence identifier")
    if not isinstance(record.get("metadata_sha256"), str) or not SHA256_RE.fullmatch(record["metadata_sha256"]):
        raise ValueError("complete metadata SHA-256 is required")
    if "service_metadata" in record:
        _validate_service_metadata(record["service_metadata"])
        _validate_field_validations(record.get("field_validations"))
    else:
        legacy = _legacy_field_validations(record)
        if set(record.get("observations", {})) != set(SERVICE_DEFINITIONS) or len(legacy) != 2:
            raise ValueError("invalid legacy field evidence")
        _validate_field_validations(legacy)
    _inspect_forbidden(payload)


def merge_field_validations(payload: dict[str, Any], existing: dict[str, Any]) -> None:
    """Merge sanitized cases by service and SAP status code, preserving prior cases."""
    record = payload["evidence"][0]
    existing_record = existing["evidence"][0]
    identity_fields = ("source_evidence_id", "metadata_sha256", "protocol", "odata_version")
    if any(record.get(field) != existing_record.get(field) for field in identity_fields):
        raise ValueError("field evidence metadata changed; reconcile it before replacing existing cases")
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for case in [*field_validations_from_record(existing_record), *field_validations_from_record(record)]:
        key = (case["service"], case["status_code"])
        previous = merged.get(key)
        if previous is not None and previous["status_business_value"] != case["status_business_value"]:
            raise ValueError(f"conflicting {case['service']} mapping for status code {case['status_code']}")
        merged[key] = case
    service_order = {"delivery": 0, "billing": 1}
    record["field_validations"] = sorted(
        merged.values(),
        key=lambda case: (service_order[case["service"]], case["status_code"]),
    )


def combined_metadata_hash(*hashes: str) -> str:
    return hashlib.sha256(":".join(hashes).encode("ascii")).hexdigest()


HTML: Final = r'''<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Phase 03 SAP SD Field Probe v1.1</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f7fb; color: #172033; }
    main { max-width: 980px; margin: 30px auto; padding: 0 20px 40px; }
    h1 { font-size: 25px; margin-bottom: 6px; }
    .subtitle { color: #526078; margin: 0 0 20px; }
    .notice { border-left: 4px solid #3568d4; background: #edf3ff; padding: 12px 16px; margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(330px,1fr)); gap: 14px; }
    .card { background: white; border: 1px solid #d8e0ec; border-radius: 10px; padding: 16px; }
    .card h2 { margin: 0 0 10px; font-size: 17px; }
    label { display: grid; gap: 5px; color: #3d4b63; font-size: 13px; margin-top: 10px; }
    input, select, button { border: 1px solid #aeb9ca; border-radius: 6px; padding: 8px 10px; font: inherit; }
    button { background: #245dcc; color: white; border-color: #245dcc; cursor: pointer; margin-top: 12px; }
    button:disabled { background: #aeb9ca; border-color: #aeb9ca; cursor: not-allowed; }
    .state { display: inline-block; border-radius: 999px; padding: 3px 9px; font-weight: 700; font-size: 12px; }
    .pending { background: #fff3cd; color: #6c5000; }
    .pass { background: #d9f5e5; color: #126538; }
    .fail { background: #fee2e2; color: #991b1b; }
    .detail { white-space: pre-wrap; color: #3d4b63; font-size: 13px; margin: 10px 0 0; }
    .local-only { color: #7b341e; font-weight: 650; }
  </style>
</head>
<body>
<main>
  <h1>Phase 03 SAP SD Delivery／Billing Field Probe v1.1</h1>
  <p class="subtitle">Chrome 直接呼叫 SAP OData V2；只保存欄位結構與 sanitized cross-check。</p>
  <div class="notice">文件號碼只存在此瀏覽器記憶體。請用 SAP UI 核對日期與狀態後再保存；localhost 不接收 raw rows。</div>
  <section class="grid">
    <article class="card" id="delivery"><h2>Outbound Delivery fields</h2><span class="state pending">等待中</span><p class="detail"></p>
      <label>Delivery document（本機暫存）<input id="delivery-id" type="password" maxlength="20" autocomplete="off"></label>
      <label>Goods Movement status code 的 SAP UI 語意
        <select id="delivery-status"><option value="">請先查詢並核對</option><option value="not_started">not_started</option><option value="partially_completed">partially_completed</option><option value="completed">completed</option><option value="other">other</option>
        </select>
      </label>
      <label><input id="delivery-confirm" type="checkbox"> 我已在 SAP UI 核對 Actual Goods Movement Date 與 Goods Movement Status</label>
      <button id="delivery-run" type="button">查詢 Delivery</button>
    </article>
    <article class="card" id="billing"><h2>Billing Document fields</h2><span class="state pending">等待中</span><p class="detail"></p>
      <label>Billing document（本機暫存）<input id="billing-id" type="password" maxlength="20" autocomplete="off"></label>
      <label>Accounting posting status code 的 SAP UI 語意
        <select id="billing-status"><option value="">請先查詢並核對</option><option value="not_relevant">not_relevant</option><option value="not_processed">not_processed</option><option value="partially_processed">partially_processed</option><option value="completely_processed">completely_processed</option>
        </select>
      </label>
      <label><input id="billing-confirm" type="checkbox"> 我已在 SAP UI 核對 Billing Document Date 與 Accounting Posting Status</label>
      <button id="billing-run" type="button">查詢 Billing</button>
    </article>
  </section>
  <article class="card" id="summary" style="margin-top:14px"><h2>Field evidence</h2><span class="state pending">等待中</span><p class="detail">每次可保存一個或兩個狀態案例；相同 metadata 下會依 service 與 status code 合併。</p><button id="save" type="button" disabled>合併保存 sanitized field case</button></article>
</main>
<script>
let config = null;
let deliveryMeta = null;
let billingMeta = null;
let deliveryObject = null;
let billingObject = null;
const cards = {delivery: document.getElementById("delivery"), billing: document.getElementById("billing"), summary: document.getElementById("summary")};
function update(id, state, detail) { const card = cards[id]; const badge = card.querySelector(".state"); badge.className = `state ${state}`; badge.textContent = state === "pass" ? "PASS" : state === "fail" ? "FAIL" : "執行中"; card.querySelector(".detail").textContent = detail; }
function authHeader() { const bytes = new TextEncoder().encode(`${config.username}:${config.password}`); let binary = ""; for (const value of bytes) binary += String.fromCharCode(value); return `Basic ${btoa(binary)}`; }
function endpoint(base, relative, query = {}) { const url = new URL(relative, base); if (config.client) url.searchParams.set("sap-client", config.client); if (config.language) url.searchParams.set("sap-language", config.language); for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value); return url; }
async function digest(text) { const bytes = new TextEncoder().encode(text); const hash = await crypto.subtle.digest("SHA-256", bytes); return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join(""); }
function redact(message) { return String(message || "unknown error").replaceAll(config.deliveryServiceUrl, "[SAP URL redacted]").replaceAll(config.billingServiceUrl, "[SAP URL redacted]").replaceAll(config.username, "[username redacted]").replaceAll(config.password, "[password redacted]"); }
async function sapGet(url, accept) { const response = await fetch(url, {method: "GET", mode: "cors", cache: "no-store", credentials: "omit", redirect: "error", headers: {Authorization: authHeader(), Accept: accept}}); const body = await response.text(); if (!response.ok) throw new Error(`HTTP ${response.status}`); return {response, body}; }
function v2Object(text) { const payload = JSON.parse(text); if (!payload || !payload.d || typeof payload.d !== "object" || Array.isArray(payload.d.results)) throw new Error("response is not an OData V2 single object"); return payload.d; }
function checkFields(meta, expected) { const names = new Set(meta.properties.map(item => item.name)); const missing = expected.filter(name => !names.has(name)); if (missing.length) throw new Error(`metadata missing: ${missing.join(", ")}`); }
async function loadMetadata(kind) {
  const def = kind === "delivery"
    ? {base: config.deliveryServiceUrl, entity: "A_OutbDeliveryHeader", fields: ["DeliveryDocument", "ActualGoodsMovementDate", "OverallGoodsMovementStatus"]}
    : {base: config.billingServiceUrl, entity: "A_BillingDocument", fields: ["BillingDocument", "BillingDocumentDate", "AccountingPostingStatus"]};
  const result = await sapGet(endpoint(def.base, "$metadata"), "application/xml");
  const xml = new DOMParser().parseFromString(result.body, "application/xml");
  if (xml.querySelector("parsererror")) throw new Error("metadata XML parse failed");
  const dataServices = Array.from(xml.getElementsByTagNameNS("*", "DataServices"))[0];
  const version = dataServices?.getAttribute("m:DataServiceVersion") || dataServices?.getAttribute("DataServiceVersion") || "unknown";
  if (version !== "2.0") throw new Error("metadata is not OData V2");
  const sets = Array.from(xml.getElementsByTagNameNS("*", "EntitySet"));
  const selected = sets.find(node => node.getAttribute("Name") === def.entity);
  if (!selected) throw new Error(`metadata missing ${def.entity}`);
  const typeName = (selected.getAttribute("EntityType") || "").split(".").pop();
  const type = Array.from(xml.getElementsByTagNameNS("*", "EntityType")).find(node => node.getAttribute("Name") === typeName);
  const properties = type
    ? Array.from(type.children).filter(node => node.localName === "Property").map(node => {
        const maxLength = node.getAttribute("MaxLength");
        return {
          name: node.getAttribute("Name"),
          edm_type: node.getAttribute("Type"),
          max_length: /^\d+$/.test(maxLength || "") ? Number(maxLength) : null,
        };
      })
    : [];
  const meta = {version, entity_set: def.entity, entity_type: typeName, entity_set_count: sets.length, properties, metadata_sha256: await digest(result.body)};
  checkFields(meta, def.fields);
  return meta;
}
function localKey(value) { if (!/^[A-Za-z0-9]{1,20}$/.test(value)) throw new Error("document ID must be 1-20 alphanumeric characters"); return value.replaceAll("'", "''"); }
async function runField(kind) { const isDelivery = kind === "delivery"; const input = document.getElementById(`${kind}-id`); const value = input.value.trim(); input.value = ""; if (!config) return; update(kind, "pending", "執行 metadata 與單筆 GET…"); try { const meta = await loadMetadata(kind); const def = isDelivery ? {base: config.deliveryServiceUrl, entity: "A_OutbDeliveryHeader", key: "DeliveryDocument", fields: ["DeliveryDocument", "ActualGoodsMovementDate", "OverallGoodsMovementStatus"]} : {base: config.billingServiceUrl, entity: "A_BillingDocument", key: "BillingDocument", fields: ["BillingDocument", "BillingDocumentDate", "AccountingPostingStatus"]}; const result = await sapGet(endpoint(def.base, `${def.entity}(${def.key}='${localKey(value)}')`, {"$select": def.fields.join(","), "$format": "json"}), "application/json"); const object = v2Object(result.body); for (const field of def.fields) if (!(field in object)) throw new Error(`response missing ${field}`); if (isDelivery) { deliveryMeta = meta; deliveryObject = object; } else { billingMeta = meta; billingObject = object; } const dateField = isDelivery ? "ActualGoodsMovementDate" : "BillingDocumentDate"; const statusField = isDelivery ? "OverallGoodsMovementStatus" : "AccountingPostingStatus"; update(kind, "pass", `metadata HTTP 200；single GET HTTP ${result.response.status}\n${dateField}: ${object[dateField] == null || object[dateField] === "" ? "empty" : "present"}\n${statusField}: ${object[statusField] == null || object[statusField] === "" ? "empty" : "present in browser memory"}`); maybeSave(); } catch (error) { update(kind, "fail", redact(error?.message)); } }
function maybeSave() {
  document.getElementById("save").disabled = !(deliveryMeta && billingMeta && (deliveryObject || billingObject));
}
function compactMetadata(meta, fields) {
  const selected = new Set(fields);
  return {
    entity_set: meta.entity_set,
    entity_type: meta.entity_type,
    metadata_sha256: meta.metadata_sha256,
    properties: meta.properties.filter(property => selected.has(property.name)),
  };
}
function readyFieldValidation(kind) {
  const object = kind === "delivery" ? deliveryObject : billingObject;
  if (!object) return null;
  const statusBusinessValue = document.getElementById(`${kind}-status`).value;
  const confirmed = document.getElementById(`${kind}-confirm`).checked;
  if (!statusBusinessValue || !confirmed) return null;
  const statusCode = kind === "delivery" ? object.OverallGoodsMovementStatus : object.AccountingPostingStatus;
  const dateValue = kind === "delivery" ? object.ActualGoodsMovementDate : object.BillingDocumentDate;
  return {
    case_kind: `${kind}_${statusBusinessValue}`,
    service: kind,
    query_status: "passed",
    returned_object: true,
    date_present: dateValue != null && dateValue !== "",
    status_code: statusCode,
    status_business_value: statusBusinessValue,
    semantic_confirmation: {
      method: "known_document_cross_check",
      confirmed_by_role: "researcher_with_sap_ui",
      confirmed_at: new Date().toISOString(),
    },
  };
}
function clearSavedCase(kind) {
  if (kind === "delivery") deliveryObject = null;
  else billingObject = null;
  document.getElementById(`${kind}-status`).value = "";
  document.getElementById(`${kind}-confirm`).checked = false;
  update(kind, "pass", "此狀態案例已合併保存；可輸入另一個 document 繼續驗證。");
}
async function saveEvidence() {
  const fieldValidations = [readyFieldValidation("delivery"), readyFieldValidation("billing")].filter(Boolean);
  if (!fieldValidations.length) {
    update("summary", "fail", "至少完成一個 document 查詢、status 語意與 SAP UI cross-check。");
    return;
  }
  const metadataHash = await digest(`${deliveryMeta.metadata_sha256}:${billingMeta.metadata_sha256}`);
  const payload = {
    evidence_version: "2.0",
    classification: "sanitized-field-evidence",
    evidence: [{
      source_evidence_id: `sap-odata-v2-fields-${metadataHash.slice(0, 16)}`,
      source_id: "webmcp.sap_sd.odata",
      service_id: "delivery_billing_services",
      protocol: "odata-v2",
      odata_version: "2.0",
      verified_at: new Date().toISOString(),
      metadata_sha256: metadataHash,
      status: "partially_verified",
      verified_bindings: [],
      service_metadata: {
        delivery: compactMetadata(deliveryMeta, ["DeliveryDocument", "ActualGoodsMovementDate", "OverallGoodsMovementStatus"]),
        billing: compactMetadata(billingMeta, ["BillingDocument", "BillingDocumentDate", "AccountingPostingStatus"]),
      },
      field_validations: fieldValidations,
      smoke_tests: {
        delivery_metadata_get: "passed",
        billing_metadata_get: "passed",
      },
      limitations: [
        "Document IDs, endpoint, credentials, raw rows and raw metadata are not stored.",
        "Semantic field bindings remain pending model reconciliation and strict validation.",
      ],
    }],
  };
  for (const item of fieldValidations) payload.evidence[0].smoke_tests[`${item.service}_single_get`] = "passed";
  try {
    const response = await fetch("/evidence", {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `local evidence save HTTP ${response.status}`);
    for (const item of fieldValidations) clearSavedCase(item.service);
    update("summary", "pass", `Sanitized field cases 已合併保存。\n累計案例：${result.case_count}`);
    maybeSave();
  } catch (error) {
    update("summary", "fail", redact(error?.message));
  }
}
async function run() { try { const response = await fetch("/config", {cache: "no-store"}); if (!response.ok) throw new Error("local /config failed"); config = await response.json(); await Promise.all([loadMetadata("delivery").then(meta => deliveryMeta = meta).catch(error => update("delivery", "fail", redact(error?.message))), loadMetadata("billing").then(meta => billingMeta = meta).catch(error => update("billing", "fail", redact(error?.message)))]); maybeSave(); } catch (error) { update("summary", "fail", String(error?.message || error)); } }
document.getElementById("delivery-run").addEventListener("click", () => runField("delivery")); document.getElementById("billing-run").addEventListener("click", () => runField("billing")); document.getElementById("save").addEventListener("click", saveEvidence); run();
</script>
</body>
</html>'''


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = "Phase03SAPSDFieldProbe/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if self.path == "/config":
            try:
                payload = json.dumps(public_configuration(self.server.env_path), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            except RuntimeError as exc:
                self._send(500, "application/json; charset=utf-8", json.dumps({"error": str(exc)}).encode("utf-8"))
            return
        if self.path == "/health":
            self._send(200, "application/json; charset=utf-8", json.dumps({"status": "ok", "probe_version": PROBE_VERSION}).encode("utf-8"))
            return
        self._send(404, "text/plain; charset=utf-8", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/evidence":
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_EVIDENCE_BYTES:
            self._send(413, "text/plain; charset=utf-8", b"invalid evidence size")
            return
        try:
            payload = json.loads(self.rfile.read(length))
            validate_sanitized_field_evidence(payload)
            self.server.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            if self.server.evidence_path.is_file():
                existing = json.loads(self.server.evidence_path.read_text(encoding="utf-8"))
                validate_sanitized_field_evidence(existing)
                merge_field_validations(payload, existing)
                validate_sanitized_field_evidence(payload)
            self.server.evidence_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            case_count = len(payload["evidence"][0]["field_validations"])
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            self._send(400, "application/json; charset=utf-8", json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8"))
            return
        response = json.dumps({"saved": True, "case_count": case_count}, separators=(",", ":")).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", response)

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


class ProbeServer(ThreadingHTTPServer):
    env_path: Path
    evidence_path: Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument("--evidence-output", type=Path, default=PROJECT_ROOT / "build" / "sap-sd-field-evidence.json")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("field probe must bind to loopback")
    try:
        public_configuration(args.env_file.resolve())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    server = ProbeServer((args.host, args.port), ProbeHandler)
    server.env_path = args.env_file.resolve()
    server.evidence_path = args.evidence_output.resolve()
    print(f"Phase 03 SAP SD field probe v{PROBE_VERSION} ready at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
