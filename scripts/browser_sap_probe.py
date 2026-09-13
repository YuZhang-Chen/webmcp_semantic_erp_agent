"""Serve a local, browser-executed SAP OData V2 connectivity probe.

The server only supplies a no-store HTML page and the local .env configuration.
All SAP requests are executed by the browser directly; this process is not a
proxy and never receives SAP response rows.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Final
from urllib.parse import urlparse


PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
DEFAULT_HOST: Final = "localhost"
DEFAULT_PORT: Final = 5173
SERVICE_NAME: Final = "API_SALES_ORDER_SRV"
PROBE_VERSION: Final = "3.5"
ALLOWED_KEYS: Final = {
    "SAP_USER",
    "SAP_PASSWORD",
    "SAP_CLIENT",
    "SAP_LANGUAGE",
    "SAP_ODATA_BASE_URL",
}
MAX_EVIDENCE_BYTES: Final = 1_000_000


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


def service_url(base_url: str) -> str:
    candidate = base_url.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError("SAP_ODATA_BASE_URL must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("SAP_ODATA_BASE_URL must not contain credentials, query, or fragment")
    if parsed.path.rstrip("/").upper().endswith("/" + SERVICE_NAME):
        return candidate + "/"
    return candidate + "/" + SERVICE_NAME + "/"


def public_configuration(env_path: Path) -> dict[str, str]:
    values = load_env(env_path)
    missing = [
        key
        for key in ("SAP_USER", "SAP_PASSWORD", "SAP_ODATA_BASE_URL")
        if not values.get(key, "").strip()
    ]
    if missing:
        raise RuntimeError("missing required .env keys: " + ", ".join(missing))
    return {
        "username": values["SAP_USER"],
        "password": values["SAP_PASSWORD"],
        "client": values.get("SAP_CLIENT", ""),
        "language": values.get("SAP_LANGUAGE", ""),
        "serviceUrl": service_url(values["SAP_ODATA_BASE_URL"]),
        "serviceName": SERVICE_NAME,
    }


HTML: Final = r"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Phase 03 Browser–SAP Evidence Probe v3.5</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f4f7fb; color: #172033; }
    main { max-width: 920px; margin: 36px auto; padding: 0 20px 40px; }
    h1 { font-size: 26px; margin-bottom: 6px; }
    .subtitle { color: #526078; margin: 0 0 24px; }
    .notice { border-left: 4px solid #3568d4; background: #edf3ff; padding: 12px 16px; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(260px,1fr)); gap: 14px; }
    .card { background: white; border: 1px solid #d8e0ec; border-radius: 10px; padding: 16px; box-shadow: 0 2px 7px #1720330d; }
    .card h2 { margin: 0 0 8px; font-size: 17px; }
    .state { display: inline-block; border-radius: 999px; padding: 3px 9px; font-weight: 700; font-size: 12px; }
    .pending { background: #fff3cd; color: #6c5000; }
    .pass { background: #d9f5e5; color: #126538; }
    .fail { background: #fee2e2; color: #991b1b; }
    .detail { white-space: pre-wrap; color: #3d4b63; font-size: 13px; margin: 10px 0 0; }
    #summary, #case-validation { margin-top: 18px; }
    .case-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(190px,1fr)); gap: 10px; align-items: end; margin-top: 14px; }
    label { display: grid; gap: 5px; color: #3d4b63; font-size: 13px; }
    input, select, button { border: 1px solid #aeb9ca; border-radius: 6px; padding: 8px 10px; font: inherit; }
    button { background: #245dcc; color: white; border-color: #245dcc; cursor: pointer; }
    button:disabled { background: #aeb9ca; border-color: #aeb9ca; cursor: not-allowed; }
    table { border-collapse: collapse; width: 100%; margin-top: 14px; font-size: 13px; }
    th, td { border-bottom: 1px solid #d8e0ec; padding: 8px; text-align: left; }
    .local-only { color: #7b341e; font-weight: 650; }
    [hidden] { display: none !important; }
    code { background: #eef1f6; padding: 2px 5px; border-radius: 4px; }
  </style>
</head>
<body>
<main>
  <h1>Phase 03 Browser–SAP Evidence Probe v3.5</h1>
  <p class="subtitle">瀏覽器直接呼叫 SAP OData V2；不經 proxy、不保存 raw rows。</p>
  <div class="notice">探針只顯示 HTTP 狀態、結構摘要與雜湊。SAP endpoint、帳密、business keys 與原始回應不會顯示。</div>
  <section class="grid">
    <article class="card" id="metadata"><h2>1. <code>$metadata</code></h2><span class="state pending">執行中</span><p class="detail"></p></article>
    <article class="card" id="entity"><h2>2. EntitySet GET</h2><span class="state pending">等待中</span><p class="detail"></p></article>
    <article class="card" id="filter"><h2>3. <code>$filter</code> GET</h2><span class="state pending">等待中</span><p class="detail"></p></article>
    <article class="card" id="transport"><h2>4. CORS／TLS／Auth</h2><span class="state pending">等待中</span><p class="detail"></p></article>
  </section>
  <article class="card" id="summary"><h2>Gate summary</h2><span class="state pending">執行中</span><p class="detail">尚未完成</p></article>
  <section class="card" id="case-validation" hidden>
    <h2>Known-case document-flow validation</h2>
    <p class="local-only">Sales Order 與 downstream document ID 只顯示於此瀏覽器記憶體；不會傳回 localhost 或寫入 evidence。請勿截圖或貼出表格內容。</p>
    <div class="case-grid">
      <label>V2 document-flow source
        <select id="case-source" disabled>
          <option>等待 V2 metadata</option>
        </select>
      </label>
      <label>案例用途
        <select id="case-kind">
          <option value="pgi_posted">已完成 PGI 的 Outbound Delivery</option>
          <option value="full_sales_flow">完整 Sales Order → Delivery → Billing</option>
        </select>
      </label>
      <label>Sales Order（本機暫存）
        <input id="case-order" type="password" inputmode="numeric" maxlength="10" autocomplete="off" spellcheck="false">
      </label>
      <button id="run-case" type="button">執行案例查詢</button>
    </div>
    <p class="detail" id="case-status">等待案例輸入。</p>
    <div id="case-results"></div>
    <button id="save-case" type="button" disabled>保存 sanitized semantic confirmation</button>
  </section>
</main>
<script>
const cards = Object.fromEntries(["metadata", "entity", "filter", "transport", "summary"].map(id => [id, document.getElementById(id)]));
let runtimeConfig = null;
let phaseEvidencePayload = null;
let currentCaseRows = [];
let phaseMetadata = null;
let currentSalesOrderStatusCode = null;

function update(id, state, detail) {
  const card = cards[id];
  const badge = card.querySelector(".state");
  badge.className = `state ${state}`;
  badge.textContent = state === "pass" ? "PASS" : state === "fail" ? "FAIL" : "執行中";
  card.querySelector(".detail").textContent = detail;
}

function redact(message, config) {
  return String(message || "unknown error")
    .replaceAll(config.serviceUrl, "[SAP service URL redacted]")
    .replaceAll(config.username, "[username redacted]")
    .replaceAll(config.password, "[password redacted]");
}

function authHeader(config) {
  const bytes = new TextEncoder().encode(`${config.username}:${config.password}`);
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return `Basic ${btoa(binary)}`;
}

function endpoint(config, relative, query = {}) {
  const url = new URL(relative, config.serviceUrl);
  if (config.client) url.searchParams.set("sap-client", config.client);
  if (config.language) url.searchParams.set("sap-language", config.language);
  for (const [key, value] of Object.entries(query)) url.searchParams.set(key, value);
  return url;
}

async function digest(text) {
  const bytes = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function sapFetchUrl(config, url, accept) {
  const response = await fetch(url, {
    method: "GET",
    mode: "cors",
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    headers: { Authorization: authHeader(config), Accept: accept },
  });
  const body = await response.text();
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { response, body };
}

async function sapFetch(config, relative, accept, query = {}) {
  return sapFetchUrl(config, endpoint(config, relative, query), accept);
}

async function diagnoseReachability(config) {
  try {
    await fetch(endpoint(config, "$metadata"), {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      credentials: "omit",
      redirect: "follow",
    });
    return {
      code: "reachable_without_cors_access",
      detail: "Unauthenticated network/TLS reachability: passed\nCredentialed CORS request: blocked before readable response\nLikely gate: CORS preflight/origin policy or authentication redirect",
    };
  } catch (_error) {
    return {
      code: "network_or_tls_unreachable",
      detail: "Unauthenticated network/TLS reachability: failed\nLikely gate: DNS, network route, TLS trust, or browser transport policy",
    };
  }
}

function localNameElements(root, name) {
  return Array.from(root.getElementsByTagNameNS("*", name));
}

function inspectMetadata(text) {
  const xml = new DOMParser().parseFromString(text, "application/xml");
  if (xml.querySelector("parsererror")) throw new Error("metadata XML parse failed");
  const dataServices = localNameElements(xml, "DataServices")[0];
  const version = dataServices?.getAttributeNS("http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "DataServiceVersion")
    || dataServices?.getAttribute("m:DataServiceVersion") || "unknown";
  const entitySets = localNameElements(xml, "EntitySet");
  const preferred = entitySets.find(node => node.getAttribute("Name") === "A_SalesOrder")
    || entitySets.find(node => /salesorder/i.test(node.getAttribute("Name") || ""));
  if (!preferred) throw new Error("no Sales Order EntitySet in tenant metadata");
  const entitySet = preferred.getAttribute("Name");
  const entityTypeName = (preferred.getAttribute("EntityType") || "").split(".").pop();
  const entityType = localNameElements(xml, "EntityType").find(node => node.getAttribute("Name") === entityTypeName);
  const propertyDefinitions = entityType
    ? localNameElements(entityType, "Property").map(node => {
      const maxLength = node.getAttribute("MaxLength")
        || node.getAttributeNS("http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "MaxLength");
      return {
        name: node.getAttribute("Name"),
        edm_type: node.getAttribute("Type"),
        max_length: /^\d+$/.test(maxLength || "") ? Number(maxLength) : null,
      };
    })
    : [];
  const properties = propertyDefinitions.map(item => item.name);
  const navigationProperties = entityType
    ? localNameElements(entityType, "NavigationProperty").map(node => node.getAttribute("Name"))
    : [];
  if (!properties.includes("SalesOrder")) throw new Error("SalesOrder property is absent from selected EntitySet");
  const documentFlowOptions = entitySets
    .filter(node => [
      "A_SalesOrderSubsqntProcFlow",
      "A_SalesOrderItmSubsqntProcFlow",
    ].includes(node.getAttribute("Name")))
    .map(node => {
      const flowEntityTypeName = (node.getAttribute("EntityType") || "").split(".").pop();
      const flowEntityType = localNameElements(xml, "EntityType").find(item => item.getAttribute("Name") === flowEntityTypeName);
      const flowProperties = flowEntityType
        ? localNameElements(flowEntityType, "Property").map(propertyNode => {
          const maxLength = propertyNode.getAttribute("MaxLength")
            || propertyNode.getAttributeNS("http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "MaxLength");
          return {
            name: propertyNode.getAttribute("Name"),
            edm_type: propertyNode.getAttribute("Type"),
            max_length: /^\d+$/.test(maxLength || "") ? Number(maxLength) : null,
          };
        })
        : [];
      return {
        entitySet: node.getAttribute("Name"),
        source: "entity_set",
        level: node.getAttribute("Name") === "A_SalesOrderSubsqntProcFlow" ? "header" : "item",
        entityType: flowEntityTypeName,
        properties: flowProperties,
      };
    });
  return {
    version,
    entitySet,
    entityType: entityTypeName,
    entitySetCount: entitySets.length,
    propertyCount: properties.length,
    properties: propertyDefinitions,
    entitySets: entitySets.map(node => ({name: node.getAttribute("Name")})),
    documentFlowOptions,
    salesOrderNavigationOptions: navigationProperties
      .filter(name => name === "to_SubsequentProcFlowDoc")
      .map(name => ({entitySet, navigation: name, source: "navigation"})),
  };
}

async function postEvidence(payload) {
  const response = await fetch("/evidence", {
    method: "POST",
    cache: "no-store",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = "unknown local validation error";
    try {
      const errorPayload = await response.json();
      detail = errorPayload.error || detail;
    } catch (_error) {
      // Keep the generic local-only message when the response is not JSON.
    }
    throw new Error(`local evidence save HTTP ${response.status}: ${detail}`);
  }
}

async function saveEvidence(config, metadata, metadataHash) {
  const payload = {
    evidence_version: "2.0",
    classification: "sanitized-build-metadata",
    evidence: [{
      source_evidence_id: `sap-odata-v2-${metadataHash.slice(0, 16)}`,
      source_id: "webmcp.sap_sd.odata",
      service_id: "sales_order_service",
      protocol: "odata-v2",
      odata_version: "2.0",
      verified_at: new Date().toISOString(),
      metadata_sha256: metadataHash,
      status: "partially_verified",
      verified_bindings: [],
      observations: {
        selected_entity_set: metadata.entitySet,
        entity_sets: metadata.entitySets,
        entity_type: metadata.entityType,
        properties: metadata.properties,
        document_flow_options: metadata.documentFlowOptions,
        sales_order_navigation_options: metadata.salesOrderNavigationOptions,
      },
      smoke_tests: {
        metadata_get: "passed",
        sales_order_collection_get: "passed",
        sales_order_filter: "passed",
      },
      limitations: [
        "V2 metadata structure and Sales Order read path are evidenced, but Delivery/Billing bindings require model reconciliation.",
        "No business keys, raw rows, endpoint, credentials, or raw metadata are stored.",
      ],
    }],
  };
  await postEvidence(payload);
  return payload;
}

function v2Rows(text) {
  const payload = JSON.parse(text);
  if (!payload || !payload.d || !Array.isArray(payload.d.results)) {
    throw new Error("response is not an OData V2 d.results collection");
  }
  return payload.d.results;
}

function v2NextLink(text) {
  const payload = JSON.parse(text);
  const link = payload && payload.d && payload.d.__next;
  if (link == null) return null;
  if (typeof link !== "string" || !link) throw new Error("invalid OData V2 next link");
  return link;
}

function assertServiceLink(config, link) {
  const next = new URL(link, config.serviceUrl);
  const base = new URL(config.serviceUrl);
  if (next.origin !== base.origin || !next.pathname.startsWith(base.pathname)) {
    throw new Error("OData V2 next link leaves the configured service root");
  }
  return next;
}

async function v2Collection(config, relative, query = {}) {
  let next = endpoint(config, relative, query);
  const rows = [];
  let pageCount = 0;
  let firstBody = null;
  let firstStatus = null;
  while (next) {
    if (++pageCount > 50) throw new Error("OData V2 pagination exceeded the safety limit");
    const result = await sapFetchUrl(config, next, "application/json");
    if (firstBody == null) {
      firstBody = result.body;
      firstStatus = result.response.status;
    }
    rows.push(...v2Rows(result.body));
    const nextLink = v2NextLink(result.body);
    next = nextLink ? assertServiceLink(config, nextLink) : null;
  }
  return {rows, pageCount, firstBody, firstStatus};
}

function odataStringLiteral(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

function salesOrderCandidates(value) {
  const candidates = [value];
  if (/^\d+$/.test(value) && value.length < 10) candidates.push(value.padStart(10, "0"));
  return [...new Set(candidates)];
}

function populateCaseSources(metadata) {
  const select = document.getElementById("case-source");
  select.replaceChildren();
  const options = [...metadata.salesOrderNavigationOptions, ...metadata.documentFlowOptions];
  const unique = new Map(options.map(option => [
    `${option.source}:${option.entitySet}:${option.navigation || ""}`,
    option,
  ]));
  metadata.caseSources = [...unique.values()];
  if (!metadata.caseSources.length) {
    const option = document.createElement("option");
    option.textContent = "V2 metadata 未暴露可核對的文件流來源";
    option.value = "";
    select.appendChild(option);
    select.disabled = true;
    document.getElementById("run-case").disabled = true;
    document.getElementById("case-status").textContent = "V2 metadata 未提供含 SalesOrder、SubsequentDocument 與 category 的文件流 binding；無法執行案例 evidence。";
    return;
  }
  metadata.caseSources.forEach((optionData, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = optionData.source === "navigation"
      ? `${optionData.entitySet}/${optionData.navigation}（Navigation）`
      : `${optionData.entitySet}（${optionData.level === "item" ? "Item-level" : "Header-level"} EntitySet）`;
    select.appendChild(option);
  });
  select.disabled = false;
}

async function fetchCaseRows(config, input, source) {
  for (const candidate of salesOrderCandidates(input)) {
    const relative = source.source === "navigation"
      ? `${source.entitySet}(${odataStringLiteral(candidate)})/${source.navigation}`
      : source.entitySet;
    const query = {
      "$top": "100",
      "$select": source.level === "item"
        ? "SalesOrder,SubsequentDocument,SubsequentDocumentCategory"
        : "SalesOrder,SubsequentDocument,SubsequentDocumentCategory,OverallSDProcessStatus,CreationDate",
      "$format": "json",
    };
    if (source.source === "entity_set") {
      query["$filter"] = `SalesOrder eq ${odataStringLiteral(candidate)}`;
    }
    const result = await v2Collection(
      config,
      relative,
      query,
    );
    const rows = result.rows;
    if (rows.some(row => String(row.SalesOrder) !== candidate)) {
      throw new Error("filtered document flow returned a different SalesOrder");
    }
    if (rows.length) return {rows, normalized: candidate !== input};
  }
  return {rows: [], normalized: false};
}

async function findSalesOrder(config, input, entitySet) {
  for (const candidate of salesOrderCandidates(input)) {
    const result = await v2Collection(
      config,
      entitySet,
      {
        "$filter": `SalesOrder eq ${odataStringLiteral(candidate)}`,
        "$top": "1",
        "$select": "SalesOrder",
        "$format": "json",
      },
    );
    const rows = result.rows;
    if (rows.some(row => String(row.SalesOrder) !== candidate)) {
      throw new Error("sales-order lookup returned a different SalesOrder");
    }
    if (rows.length) return {exists: true, normalized: candidate !== input};
  }
  return {exists: false, normalized: false};
}

async function fetchSalesOrderStatus(config, input, entitySet) {
  for (const candidate of salesOrderCandidates(input)) {
    const result = await v2Collection(
      config,
      entitySet,
      {
        "$filter": `SalesOrder eq ${odataStringLiteral(candidate)}`,
        "$top": "1",
        "$select": "SalesOrder,OverallSDProcessStatus",
        "$format": "json",
      },
    );
    const rows = result.rows;
    if (rows.some(row => String(row.SalesOrder) !== candidate)) {
      throw new Error("sales-order status lookup returned a different SalesOrder");
    }
    if (rows.length) {
      const code = rows[0].OverallSDProcessStatus;
      if (typeof code !== "string" || !/^[A-Z]$/.test(code)) {
        throw new Error("Sales Order status property was not a single SAP code");
      }
      return code;
    }
  }
  return null;
}

function appendCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value == null || value === "" ? "(null)" : String(value);
  row.appendChild(cell);
}

function renderCaseRows(rows) {
  const host = document.getElementById("case-results");
  host.replaceChildren();
  const table = document.createElement("table");
  const header = document.createElement("tr");
  for (const label of ["Downstream document（僅本機）", "Category code", "Process status", "Creation date", "業務分類確認"]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    header.appendChild(cell);
  }
  table.appendChild(header);
  const categories = new Map();
  for (const item of rows) {
    const row = document.createElement("tr");
    appendCell(row, item.SubsequentDocument);
    appendCell(row, item.SubsequentDocumentCategory);
    appendCell(row, item.OverallSDProcessStatus);
    appendCell(row, item.CreationDate);
    const mappingCell = document.createElement("td");
    const code = String(item.SubsequentDocumentCategory || "");
    let select = categories.get(code);
    if (!select) {
      select = document.createElement("select");
      select.className = "category-mapping";
      select.dataset.categoryCode = code;
      for (const [value, label] of [
        ["", "請依 SAP UI 核對"],
        ["outbound_delivery", "Outbound Delivery"],
        ["billing_document", "Billing Document"],
        ["other", "Other／不納入"],
      ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
      }
      categories.set(code, select);
    }
    mappingCell.appendChild(select.cloneNode(true));
    row.appendChild(mappingCell);
    table.appendChild(row);
  }
  host.appendChild(table);

  for (const select of host.querySelectorAll("select.category-mapping")) {
    select.addEventListener("change", () => {
      const code = select.dataset.categoryCode;
      for (const peer of host.querySelectorAll("select.category-mapping")) {
        if (peer.dataset.categoryCode === code) peer.value = select.value;
      }
    });
  }

  const statusHost = document.createElement("div");
  statusHost.className = "case-grid";
  const statusLabel = document.createElement("label");
  statusLabel.textContent = "OverallSDProcessStatus 業務語意（請以 SAP UI 核對）";
  const statusSelect = document.createElement("select");
  statusSelect.className = "status-mapping";
  statusSelect.dataset.statusCode = currentSalesOrderStatusCode || "";
  for (const [value, label] of [
    ["", "請依 SAP UI 核對"],
    ["not_started", "尚未開始"],
    ["partially_completed", "部分完成"],
    ["completed", "完成"],
  ]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    statusSelect.appendChild(option);
  }
  statusLabel.appendChild(statusSelect);
  statusHost.appendChild(statusLabel);
  host.appendChild(statusHost);
}

async function runCaseValidation() {
  const status = document.getElementById("case-status");
  const saveButton = document.getElementById("save-case");
  const input = document.getElementById("case-order");
  const sourceIndex = Number(document.getElementById("case-source").value);
  const salesOrder = input.value.trim();
  input.value = "";
  currentCaseRows = [];
  currentSalesOrderStatusCode = null;
  saveButton.disabled = true;
  document.getElementById("case-results").replaceChildren();
  if (!runtimeConfig || !phaseEvidencePayload || !phaseMetadata) {
    status.textContent = "Browser gate 尚未完成。";
    return;
  }
  const source = Number.isInteger(sourceIndex) && phaseMetadata.caseSources?.[sourceIndex];
  if (!source) {
    status.textContent = "V2 metadata 沒有可用的文件流 binding source。";
    return;
  }
  if (!/^[A-Za-z0-9]{1,10}$/.test(salesOrder)) {
    status.textContent = "Sales Order 必須是 1–10 個英數字元；輸入值未保存。";
    return;
  }
  status.textContent = "執行唯讀文件流查詢；輸入值不會傳回 localhost。";
  try {
    const result = await fetchCaseRows(runtimeConfig, salesOrder, source);
    const rows = result.rows;
    currentCaseRows = rows;
    if (!rows.length) {
      const order = await findSalesOrder(runtimeConfig, salesOrder, phaseMetadata.entitySet);
      if (order.exists) {
        status.textContent = "Sales Order 在 SAP 中存在，但 subsequent process-flow 為空；沒有可保存的 category evidence。請確認該單確實有 Outbound Delivery／Billing，且已由此 V2 service 暴露。";
      } else {
        status.textContent = "查詢成功但找不到此 Sales Order；沒有可保存的 category evidence。";
      }
      return;
    }
    currentSalesOrderStatusCode = await fetchSalesOrderStatus(
      runtimeConfig,
      salesOrder,
      phaseMetadata.entitySet,
    );
    if (!currentSalesOrderStatusCode) {
      status.textContent = "文件流查詢成功，但找不到 Sales Order header status；沒有可保存的 status evidence。";
      return;
    }
    renderCaseRows(rows);
    status.textContent = "查詢成功。請用 SAP UI 核對 downstream document 與 OverallSDProcessStatus，再完成兩組業務分類。";
    saveButton.disabled = false;
  } catch (error) {
    status.textContent = `案例查詢失敗：${redact(error?.message, runtimeConfig)}`;
  }
}

async function saveCaseValidation() {
  const status = document.getElementById("case-status");
  const caseKind = document.getElementById("case-kind").value;
  const mappings = new Map();
  for (const select of document.querySelectorAll("select.category-mapping")) {
    const code = select.dataset.categoryCode;
    const value = select.value;
    if (!code || !value) {
      status.textContent = "每個非空 category code 都必須先完成業務分類。";
      return;
    }
    mappings.set(code, value);
  }
  const values = new Set(mappings.values());
  if (!values.has("outbound_delivery")) {
    status.textContent = "此案例尚未確認任何 Outbound Delivery category。";
    return;
  }
  if (caseKind === "full_sales_flow" && !values.has("billing_document")) {
    status.textContent = "完整銷售流程案例必須同時確認 Billing Document category。";
    return;
  }
  const statusSelect = document.querySelector("select.status-mapping");
  const statusValue = statusSelect?.value || "";
  const statusCode = statusSelect?.dataset.statusCode || "";
  if (!statusCode || !statusValue) {
    status.textContent = "請先在 SAP UI 核對 OverallSDProcessStatus 並選擇業務語意。";
    return;
  }
  const record = phaseEvidencePayload.evidence[0];
  const validations = Array.isArray(record.case_validations) ? record.case_validations : [];
  const sanitized = {
    case_kind: caseKind,
    query_status: "passed",
    returned_rows: currentCaseRows.length > 0,
    category_mappings: Array.from(mappings, ([category_code, business_value]) => ({
      category_code,
      business_value,
    })),
    semantic_confirmation: {
      method: "known_case_cross_check",
      confirmed_by_role: "researcher_with_sap_ui",
      confirmed_at: new Date().toISOString(),
    },
  };
  record.case_validations = [
    ...validations.filter(item => item.case_kind !== caseKind),
    sanitized,
  ];
  const statusValidations = Array.isArray(record.sales_order_status_validations)
    ? record.sales_order_status_validations
    : [];
  record.sales_order_status_validations = [
    ...statusValidations.filter(item => item.status_code !== statusCode),
    {
      case_kind: caseKind,
      query_status: "passed",
      returned_object: true,
      status_code: statusCode,
      status_business_value: statusValue,
      semantic_confirmation: {
        method: "known_case_cross_check",
        confirmed_by_role: "researcher_with_sap_ui",
        confirmed_at: new Date().toISOString(),
      },
    },
  ];
  try {
    await postEvidence(phaseEvidencePayload);
    currentCaseRows = [];
    currentSalesOrderStatusCode = null;
    document.getElementById("case-results").replaceChildren();
    document.getElementById("save-case").disabled = true;
    status.textContent = "Sanitized semantic confirmation 已保存；business key 與 raw rows 已從頁面清除。";
  } catch (error) {
    status.textContent = `Sanitized evidence 保存失敗：${redact(error?.message, runtimeConfig)}`;
  }
}

document.getElementById("run-case").addEventListener("click", runCaseValidation);
document.getElementById("save-case").addEventListener("click", saveCaseValidation);

async function run() {
  let config;
  try {
    const configResponse = await fetch("/config", { cache: "no-store" });
    if (!configResponse.ok) throw new Error(`local config HTTP ${configResponse.status}`);
    config = await configResponse.json();
    const metadataResult = await sapFetch(config, "$metadata", "application/xml");
    const metadata = inspectMetadata(metadataResult.body);
    if (!String(metadata.version).startsWith("2")) throw new Error(`tenant reports OData ${metadata.version}, expected V2`);
    phaseMetadata = metadata;
    const metadataHash = await digest(metadataResult.body);
    update("metadata", "pass", `HTTP ${metadataResult.response.status}\nOData ${metadata.version}\nEntitySets: ${metadata.entitySetCount}\nSelected: ${metadata.entitySet}\nMetadata SHA-256: ${metadataHash.slice(0, 16)}…`);

    const entityResult = await v2Collection(config, metadata.entitySet, { "$top": "1", "$select": "SalesOrder", "$format": "json" });
    const rows = entityResult.rows;
    if (rows.length < 1 || rows[0].SalesOrder == null) throw new Error("EntitySet returned no usable SalesOrder row");
    const entityHash = await digest(entityResult.firstBody || "");
    update("entity", "pass", `HTTP ${entityResult.firstStatus}\nV2 collection shape: d.results\nRows: ${rows.length}\nBody SHA-256: ${entityHash.slice(0, 16)}…\nBusiness key: redacted`);

    const salesOrder = String(rows[0].SalesOrder);
    const filterResult = await v2Collection(config, metadata.entitySet, { "$filter": `SalesOrder eq ${odataStringLiteral(salesOrder)}`, "$top": "1", "$select": "SalesOrder", "$format": "json" });
    const filteredRows = filterResult.rows;
    if (filteredRows.length < 1 || String(filteredRows[0].SalesOrder) !== salesOrder) {
      throw new Error("filtered response did not return the derived SalesOrder key");
    }
    const filterHash = await digest(filterResult.firstBody || "");
    update("filter", "pass", `HTTP ${filterResult.firstStatus}\nFilter property: SalesOrder\nFilter value: derived then redacted\nRows: ${filteredRows.length}\nBody SHA-256: ${filterHash.slice(0, 16)}…\nPages: ${filterResult.pageCount}`);

    update("transport", "pass", `Cross-origin Authorization request succeeded\nCORS preflight capability: passed\nHTTPS request: completed in this browser session\nCertificate exceptions previously accepted by the user cannot be detected by this probe\nAuthentication: accepted\nCredential persistence: none`);
    let evidenceId;
    try {
      phaseEvidencePayload = await saveEvidence(config, metadata, metadataHash);
      evidenceId = phaseEvidencePayload.evidence[0].source_evidence_id;
    } catch (error) {
      const safe = redact(error?.message, config);
      update("summary", "fail", `${config.serviceName} SAP browser gate passed, but sanitized evidence was not saved.\n${safe}`);
      window.__PHASE03_RESULT__ = { status: "evidence_save_failed", service: config.serviceName, odataVersion: metadata.version, entitySet: metadata.entitySet };
      return;
    }
    update("summary", "pass", `${config.serviceName} browser gate passed.\nAll SAP calls were direct browser GET requests.\nSanitized evidence: ${evidenceId}`);
    runtimeConfig = config;
    populateCaseSources(metadata);
    document.getElementById("case-validation").hidden = false;
    window.__PHASE03_RESULT__ = { status: "passed", service: config.serviceName, odataVersion: metadata.version, entitySet: metadata.entitySet, evidenceId };
  } catch (error) {
    const safe = config ? redact(error?.message, config) : String(error?.message || error);
    let diagnostic = { code: "local_configuration_failed", detail: "SAP request was not started" };
    if (config) diagnostic = await diagnoseReachability(config);
    if (cards.metadata.querySelector(".state").classList.contains("pending")) {
      update("metadata", "fail", `Credentialed browser GET failed before a readable HTTP response\nBrowser error: ${safe}`);
    }
    if (cards.entity.querySelector(".state").classList.contains("pending")) update("entity", "fail", "Stopped after metadata gate failure");
    if (cards.filter.querySelector(".state").classList.contains("pending")) update("filter", "fail", "Stopped after metadata gate failure");
    update("transport", "fail", diagnostic.detail);
    update("summary", "fail", `Gate stopped: ${diagnostic.code}\nNo fallback, proxy, mock, or TLS bypass was used.`);
    window.__PHASE03_RESULT__ = { status: "failed", reason: diagnostic.code };
  }
}

run();
</script>
</body>
</html>
"""


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = f"Phase03EvidenceProbe/{PROBE_VERSION}"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, "text/html; charset=utf-8", HTML.encode("utf-8"))
            return
        if self.path == "/config":
            try:
                payload = json.dumps(
                    public_configuration(self.server.env_path),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                self._send(200, "application/json; charset=utf-8", payload)
            except RuntimeError as exc:
                payload = json.dumps({"error": str(exc)}, separators=(",", ":")).encode("utf-8")
                self._send(500, "application/json; charset=utf-8", payload)
            return
        if self.path == "/health":
            payload = json.dumps(
                {"status": "ok", "probe_version": PROBE_VERSION},
                separators=(",", ":"),
            ).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", payload)
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
            validate_sanitized_evidence(payload)
            if self.server.evidence_path.is_file():
                existing = json.loads(self.server.evidence_path.read_text(encoding="utf-8"))
                validate_sanitized_evidence(existing)
                merge_case_validations(payload, existing)
                merge_sales_order_status_validations(payload, existing)
                validate_sanitized_evidence(payload)
            self.server.evidence_path.parent.mkdir(parents=True, exist_ok=True)
            self.server.evidence_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            body = json.dumps({"error": str(exc)}, separators=(",", ":")).encode("utf-8")
            self._send(400, "application/json; charset=utf-8", body)
            return
        body = json.dumps({"saved": True}, separators=(",", ":")).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body)

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


def validate_sanitized_evidence(payload: object) -> None:
    if (
        not isinstance(payload, dict)
        or payload.get("evidence_version") != "2.0"
        or payload.get("classification") != "sanitized-build-metadata"
    ):
        raise ValueError("invalid evidence envelope")
    records = payload.get("evidence")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise ValueError("exactly one evidence record is required")
    record = records[0]
    if (
        record.get("source_id") != "webmcp.sap_sd.odata"
        or record.get("protocol") != "odata-v2"
        or record.get("odata_version") != "2.0"
    ):
        raise ValueError("unexpected source or protocol")
    if not str(record.get("source_evidence_id", "")).startswith("sap-odata-v2-"):
        raise ValueError("V2 evidence must use a V2 source evidence identifier")
    metadata_hash = record.get("metadata_sha256")
    if not isinstance(metadata_hash, str) or len(metadata_hash) != 64:
        raise ValueError("complete metadata SHA-256 is required")
    validate_case_validations(record)
    validate_sales_order_status_validations(record)
    forbidden_keys = {
        "authorization",
        "business_key",
        "business_keys",
        "credential",
        "credentials",
        "endpoint",
        "password",
        "raw_metadata",
        "raw_row",
        "raw_rows",
        "service_url",
        "username",
    }

    def inspect(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden_keys:
                    raise ValueError(f"evidence contains forbidden key: {key}")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
        elif isinstance(value, str) and ("https://" in value.lower() or "http://" in value.lower()):
            raise ValueError("evidence contains forbidden endpoint material")

    inspect(payload)


def merge_case_validations(payload: dict[str, object], existing: dict[str, object]) -> None:
    """Preserve sanitized known cases when the page is reloaded for the same metadata."""
    record = payload["evidence"][0]  # type: ignore[index]
    existing_record = existing["evidence"][0]  # type: ignore[index]
    identity_fields = ("source_evidence_id", "metadata_sha256", "protocol", "odata_version")
    if any(record.get(field) != existing_record.get(field) for field in identity_fields):
        return
    cases_by_kind = {
        case["case_kind"]: case
        for case in existing_record.get("case_validations", [])
    }
    cases_by_kind.update(
        {
            case["case_kind"]: case
            for case in record.get("case_validations", [])
        }
    )
    if cases_by_kind:
        record["case_validations"] = [
            cases_by_kind[kind]
            for kind in ("pgi_posted", "full_sales_flow")
            if kind in cases_by_kind
        ]


def merge_sales_order_status_validations(
    payload: dict[str, object], existing: dict[str, object]
) -> None:
    """Preserve sanitized Sales Order status cases for the same metadata."""
    record = payload["evidence"][0]  # type: ignore[index]
    existing_record = existing["evidence"][0]  # type: ignore[index]
    identity_fields = ("source_evidence_id", "metadata_sha256", "protocol", "odata_version")
    if any(record.get(field) != existing_record.get(field) for field in identity_fields):
        return
    by_code = {
        case["status_code"]: case
        for case in existing_record.get("sales_order_status_validations", [])
    }
    by_code.update(
        {
            case["status_code"]: case
            for case in record.get("sales_order_status_validations", [])
        }
    )
    if by_code:
        record["sales_order_status_validations"] = [
            by_code[code] for code in sorted(by_code)
        ]


def validate_case_validations(record: dict[str, object]) -> None:
    validations = record.get("case_validations", [])
    if not isinstance(validations, list) or len(validations) > 2:
        raise ValueError("case_validations must contain at most two sanitized cases")
    allowed_case_keys = {
        "case_kind",
        "query_status",
        "returned_rows",
        "category_mappings",
        "semantic_confirmation",
    }
    allowed_confirmation_keys = {
        "method",
        "confirmed_by_role",
        "confirmed_at",
    }
    seen_cases: set[str] = set()
    category_meanings: dict[str, str] = {}
    for case in validations:
        if not isinstance(case, dict) or set(case) != allowed_case_keys:
            raise ValueError("case validation contains unknown or missing fields")
        case_kind = case.get("case_kind")
        if case_kind not in {"pgi_posted", "full_sales_flow"} or case_kind in seen_cases:
            raise ValueError("case_kind must be unique and allowlisted")
        seen_cases.add(str(case_kind))
        if case.get("query_status") != "passed" or case.get("returned_rows") is not True:
            raise ValueError("saved case validation must represent a successful non-empty query")
        mappings = case.get("category_mappings")
        if not isinstance(mappings, list) or not mappings:
            raise ValueError("case validation requires category mappings")
        case_meanings: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict) or set(mapping) != {"category_code", "business_value"}:
                raise ValueError("category mapping contains unknown or missing fields")
            code = mapping.get("category_code")
            meaning = mapping.get("business_value")
            if (
                not isinstance(code, str)
                or not 1 <= len(code) <= 4
                or not code.isprintable()
                or code.strip() != code
            ):
                raise ValueError("category code must be 1-4 printable non-space characters")
            if meaning not in {"outbound_delivery", "billing_document", "other"}:
                raise ValueError("business category is not allowlisted")
            prior = category_meanings.setdefault(code, str(meaning))
            if prior != meaning:
                raise ValueError("the same category code has conflicting business meanings")
            case_meanings.add(str(meaning))
        if "outbound_delivery" not in case_meanings:
            raise ValueError("each saved case must confirm an outbound delivery category")
        if case_kind == "full_sales_flow" and "billing_document" not in case_meanings:
            raise ValueError("full sales flow must confirm a billing document category")
        confirmation = case.get("semantic_confirmation")
        if not isinstance(confirmation, dict) or set(confirmation) != allowed_confirmation_keys:
            raise ValueError("semantic confirmation contains unknown or missing fields")
        if confirmation.get("method") != "known_case_cross_check":
            raise ValueError("semantic confirmation method is not allowlisted")
        if confirmation.get("confirmed_by_role") != "researcher_with_sap_ui":
            raise ValueError("semantic confirmation role is not allowlisted")
        confirmed_at = confirmation.get("confirmed_at")
        if not isinstance(confirmed_at, str) or not confirmed_at.endswith("Z"):
            raise ValueError("semantic confirmation requires an RFC 3339 UTC timestamp")


def validate_sales_order_status_validations(record: dict[str, object]) -> None:
    validations = record.get("sales_order_status_validations", [])
    if not isinstance(validations, list) or len(validations) > 16:
        raise ValueError("sales_order_status_validations must contain at most sixteen cases")
    allowed_keys = {
        "case_kind",
        "query_status",
        "returned_object",
        "status_code",
        "status_business_value",
        "semantic_confirmation",
    }
    allowed_case_kinds = {"pgi_posted", "full_sales_flow"}
    allowed_values = {"not_started", "partially_completed", "completed"}
    allowed_confirmation_keys = {"method", "confirmed_by_role", "confirmed_at"}
    meanings: dict[str, str] = {}
    for case in validations:
        if not isinstance(case, dict) or set(case) != allowed_keys:
            raise ValueError("sales-order status validation contains unknown or missing fields")
        if case.get("case_kind") not in allowed_case_kinds:
            raise ValueError("sales-order status case_kind is not allowlisted")
        if case.get("query_status") != "passed" or case.get("returned_object") is not True:
            raise ValueError("saved Sales Order status case must be a successful object query")
        code = case.get("status_code")
        value = case.get("status_business_value")
        if not isinstance(code, str) or not 1 <= len(code) <= 4 or code.strip() != code:
            raise ValueError("Sales Order status code must be 1-4 non-space characters")
        if value not in allowed_values:
            raise ValueError("Sales Order status business value is not allowlisted")
        prior = meanings.setdefault(code, str(value))
        if prior != value:
            raise ValueError("the same Sales Order status code has conflicting meanings")
        confirmation = case.get("semantic_confirmation")
        if not isinstance(confirmation, dict) or set(confirmation) != allowed_confirmation_keys:
            raise ValueError("Sales Order status confirmation contains unknown or missing fields")
        if confirmation.get("method") != "known_case_cross_check":
            raise ValueError("Sales Order status confirmation method is not allowlisted")
        if confirmation.get("confirmed_by_role") != "researcher_with_sap_ui":
            raise ValueError("Sales Order status confirmation role is not allowlisted")
        if not isinstance(confirmation.get("confirmed_at"), str) or not confirmation["confirmed_at"].endswith("Z"):
            raise ValueError("Sales Order status confirmation requires an RFC 3339 UTC timestamp")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=PROJECT_ROOT / "build" / "sap-metadata-evidence.json",
    )
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("browser probe must bind to loopback")
    public_configuration(args.env_file.resolve())
    server = ProbeServer((args.host, args.port), ProbeHandler)
    server.env_path = args.env_file.resolve()
    server.evidence_path = args.evidence_output.resolve()
    print(
        f"Phase 03 evidence probe v{PROBE_VERSION} ready at http://{args.host}:{args.port}/",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
