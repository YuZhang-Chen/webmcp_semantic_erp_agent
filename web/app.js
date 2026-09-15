const $ = (selector) => document.querySelector(selector);
const status = { webmcp: $("#webmcp-status"), sap: $("#sap-status") };
const variantNotes = {
  technical: "僅提供 OData 實體集與技術欄位名稱。",
  typed: "提供型別、參數結構與一般功能描述。",
  semantic: "商業語意、文件關係與唯讀政策皆由模型編譯產生。",
};

function setPill(node, text, kind) { node.textContent = text; node.className = `pill ${kind}`; }
function currentOrderId() { return new FormData($("#query-form")).get("sales_order_id")?.trim(); }

async function callTool(operation, args) {
  const message = $("#message");
  message.className = "message"; message.textContent = "正在以唯讀 OData 查詢…";
  try {
    const response = await fetch(`/api/tools/${encodeURIComponent(operation)}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(args)});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    render(operation, payload); return payload;
  } catch (error) {
    message.className = "message error"; message.textContent = String(error.message || error); throw error;
  }
}

function render(operation, payload) {
  const rows = payload.rows || [];
  $("#result-title").textContent = `${operation} · ${payload.row_count} 筆`;
  $("#message").textContent = rows.length ? "查詢完成。僅呈現語意模型允許的欄位。" : "查詢完成，但沒有符合條件的文件。";
  const columns = [...new Set(rows.flatMap(Object.keys))];
  $("#results thead").innerHTML = columns.length ? `<tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join("")}</tr>` : "";
  $("#results tbody").innerHTML = rows.map(row => `<tr>${columns.map(c => `<td>${escapeHtml(row[c] ?? "")}</td>`).join("")}</tr>`).join("");
  $("#provenance").textContent = `source=${payload.source_classification} · protocol=${payload.protocol} · model=${payload.model_version} · retrieved_at=${payload.retrieved_at} · request_id=${payload.request_id || "n/a"}`;
}

function escapeHtml(value) { const div = document.createElement("div"); div.textContent = String(value); return div.innerHTML; }

$("#query-form").addEventListener("submit", (event) => {
  event.preventDefault(); const args = Object.fromEntries([...new FormData(event.currentTarget)].filter(([,v]) => v !== ""));
  if (args.limit) args.limit = Number(args.limit); callTool("search_sales_orders", args).catch(() => {});
});
document.querySelectorAll("[data-operation]").forEach(button => button.addEventListener("click", () => {
  const sales_order_id = currentOrderId();
  if (!sales_order_id) { $("#message").className="message error"; $("#message").textContent="請先輸入銷售訂單編號。"; return; }
  callTool(button.dataset.operation, {sales_order_id}).catch(() => {});
}));
$("#variant").value = new URLSearchParams(location.search).get("variant") || "semantic";
$("#variant").addEventListener("change", (event) => { const url=new URL(location); url.searchParams.set("variant", event.target.value); location.href=url; });
$("#variant-note").textContent = variantNotes[$("#variant").value];

window.addEventListener("erp-webmcp-ready", () => setPill(status.webmcp, "WebMCP 已註冊", "ok"));
window.addEventListener("erp-webmcp-unavailable", () => setPill(status.webmcp, "瀏覽器不支援 WebMCP", "warn"));
window.addEventListener("erp-webmcp-error", () => setPill(status.webmcp, "WebMCP 註冊失敗", "bad"));
const catalog = window.__ERP_WEBMCP_CATALOG__;
if (catalog) { $("#model-version").textContent = catalog.modelVersion; $("#model-hash").textContent = catalog.modelSha256; }
fetch("/api/health").then(r => r.json()).then(data => {
  const count=Object.values(data.services).filter(x=>x.configured).length;
  setPill(status.sap, count===3 ? `SAP ${data.protocol} 已設定` : `SAP 服務 ${count}/3 已設定`, count===3 ? "ok" : "warn");
}).catch(() => setPill(status.sap, "後端無法連線", "bad"));
