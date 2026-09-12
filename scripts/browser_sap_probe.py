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
ALLOWED_KEYS: Final = {
    "SAP_USER",
    "SAP_PASSWORD",
    "SAP_CLIENT",
    "SAP_LANGUAGE",
    "SAP_ODATA_BASE_URL",
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
  <title>Phase 01 Browser–SAP Probe</title>
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
    #summary { margin-top: 18px; }
    code { background: #eef1f6; padding: 2px 5px; border-radius: 4px; }
  </style>
</head>
<body>
<main>
  <h1>Phase 01 Browser–SAP 連線閘門</h1>
  <p class="subtitle">瀏覽器直接呼叫 SAP OData V2；不經 proxy、不保存 raw rows。</p>
  <div class="notice">探針只顯示 HTTP 狀態、結構摘要與雜湊。SAP endpoint、帳密、business keys 與原始回應不會顯示。</div>
  <section class="grid">
    <article class="card" id="metadata"><h2>1. <code>$metadata</code></h2><span class="state pending">執行中</span><p class="detail"></p></article>
    <article class="card" id="entity"><h2>2. EntitySet GET</h2><span class="state pending">等待中</span><p class="detail"></p></article>
    <article class="card" id="filter"><h2>3. <code>$filter</code> GET</h2><span class="state pending">等待中</span><p class="detail"></p></article>
    <article class="card" id="transport"><h2>4. CORS／TLS／Auth</h2><span class="state pending">等待中</span><p class="detail"></p></article>
  </section>
  <article class="card" id="summary"><h2>Gate summary</h2><span class="state pending">執行中</span><p class="detail">尚未完成</p></article>
</main>
<script>
const cards = Object.fromEntries(["metadata", "entity", "filter", "transport", "summary"].map(id => [id, document.getElementById(id)]));

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

async function sapFetch(config, relative, accept, query = {}) {
  const response = await fetch(endpoint(config, relative, query), {
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
  const properties = entityType ? localNameElements(entityType, "Property").map(node => node.getAttribute("Name")) : [];
  if (!properties.includes("SalesOrder")) throw new Error("SalesOrder property is absent from selected EntitySet");
  return { version, entitySet, entitySetCount: entitySets.length, propertyCount: properties.length };
}

function v2Rows(text) {
  const payload = JSON.parse(text);
  if (!payload || !payload.d || !Array.isArray(payload.d.results)) {
    throw new Error("response is not an OData V2 d.results collection");
  }
  return payload.d.results;
}

async function run() {
  let config;
  try {
    const configResponse = await fetch("/config", { cache: "no-store" });
    if (!configResponse.ok) throw new Error(`local config HTTP ${configResponse.status}`);
    config = await configResponse.json();
    const metadataResult = await sapFetch(config, "$metadata", "application/xml");
    const metadata = inspectMetadata(metadataResult.body);
    if (!String(metadata.version).startsWith("2")) throw new Error(`tenant reports OData ${metadata.version}, expected V2`);
    const metadataHash = await digest(metadataResult.body);
    update("metadata", "pass", `HTTP ${metadataResult.response.status}\nOData ${metadata.version}\nEntitySets: ${metadata.entitySetCount}\nSelected: ${metadata.entitySet}\nMetadata SHA-256: ${metadataHash.slice(0, 16)}…`);

    const entityResult = await sapFetch(config, metadata.entitySet, "application/json", { "$top": "1", "$select": "SalesOrder", "$format": "json" });
    const rows = v2Rows(entityResult.body);
    if (rows.length < 1 || rows[0].SalesOrder == null) throw new Error("EntitySet returned no usable SalesOrder row");
    const entityHash = await digest(entityResult.body);
    update("entity", "pass", `HTTP ${entityResult.response.status}\nV2 collection shape: d.results\nRows: ${rows.length}\nBody SHA-256: ${entityHash.slice(0, 16)}…\nBusiness key: redacted`);

    const salesOrder = String(rows[0].SalesOrder);
    const literal = `'${salesOrder.replaceAll("'", "''")}'`;
    const filterResult = await sapFetch(config, metadata.entitySet, "application/json", { "$filter": `SalesOrder eq ${literal}`, "$top": "1", "$select": "SalesOrder", "$format": "json" });
    const filteredRows = v2Rows(filterResult.body);
    if (filteredRows.length < 1 || String(filteredRows[0].SalesOrder) !== salesOrder) {
      throw new Error("filtered response did not return the derived SalesOrder key");
    }
    const filterHash = await digest(filterResult.body);
    update("filter", "pass", `HTTP ${filterResult.response.status}\nFilter property: SalesOrder\nFilter value: derived then redacted\nRows: ${filteredRows.length}\nBody SHA-256: ${filterHash.slice(0, 16)}…`);

    update("transport", "pass", `Cross-origin Authorization request succeeded\nCORS preflight capability: passed\nHTTPS request: completed in this browser session\nCertificate exceptions previously accepted by the user cannot be detected by this probe\nAuthentication: accepted\nCredential persistence: none`);
    update("summary", "pass", `${config.serviceName} browser gate passed.\nAll SAP calls were direct browser GET requests.`);
    window.__PHASE01_RESULT__ = { status: "passed", service: config.serviceName, odataVersion: metadata.version, entitySet: metadata.entitySet };
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
    window.__PHASE01_RESULT__ = { status: "failed", reason: diagnostic.code };
  }
}

run();
</script>
</body>
</html>
"""


class ProbeHandler(BaseHTTPRequestHandler):
    server_version = "Phase01Probe/1.0"

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
        self._send(404, "text/plain; charset=utf-8", b"not found")

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("browser probe must bind to loopback")
    public_configuration(args.env_file.resolve())
    server = ProbeServer((args.host, args.port), ProbeHandler)
    server.env_path = args.env_file.resolve()
    print(f"Phase 01 browser probe ready at http://{args.host}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
