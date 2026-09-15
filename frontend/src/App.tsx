import { useEffect, useRef, useState } from "react";
import { AlertTriangle, ChevronRight, CircleHelp, Database, Loader2, Search, Server, ShieldCheck, Truck, ReceiptText } from "lucide-react";
import { loadRuntime } from "./runtime/config";
import type { BillingList, CanonicalCriteria, DeliveryList, LoadState, RuntimeConfig, RuntimeArtifact, SalesOrderDetail, SalesOrderList, ToolCatalog } from "./runtime/types";
import { ActionFailure, ODataClient } from "./runtime/odata";
import { registerConditionTools } from "../../prototype/webmcp/register-semantic-tools.mjs";

type ModelContext = { registerTool: (tool: Record<string, unknown>, options: { signal: AbortSignal }) => Promise<void> };
type Operation = "search_sales_orders" | "get_sales_order" | "get_related_deliveries" | "get_related_billing_documents";
type Slice<T> = LoadState<T>;

const empty = <T,>(): Slice<T> => ({ loading: false, data: null, error: "" });
const initialCriteria: CanonicalCriteria = {};

function formatDate(value: string | null | undefined) { return value || "—"; }
function statusLabel(value: string | null | undefined) {
  return ({ not_started: "尚未開始", partially_completed: "部分完成", completed: "已完成", not_relevant: "不適用", not_processed: "尚未處理", partially_processed: "部分處理", completely_processed: "已完成" } as Record<string, string>)[value ?? ""] ?? "—";
}
function StatusPill({ value }: { value: string | null | undefined }) { return <span className={`status-pill status-${value ?? "unknown"}`}>{statusLabel(value)}</span>; }
function Loading({ label }: { label: string }) { return <div className="inline-state" aria-live="polite"><Loader2 className="spin" size={18} /><span>{label}</span></div>; }
function Empty({ message }: { message: string }) { return <div className="inline-state muted"><CircleHelp size={18} /><span>{message}</span></div>; }
function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) { return <div className="error-box" role="alert"><AlertTriangle size={18} /><span>{message}</span>{onRetry ? <button className="text-button" type="button" onClick={onRetry}>重試</button> : null}</div>; }

function App() {
  const [runtime, setRuntime] = useState<{ config: RuntimeConfig; catalog: ToolCatalog; bindings: RuntimeArtifact } | null>(null);
  const [bootError, setBootError] = useState("");
  const [registration, setRegistration] = useState<"loading" | "ready" | "unavailable" | "error">("loading");
  const [criteria, setCriteria] = useState<CanonicalCriteria>(initialCriteria);
  const [orderIdInput, setOrderIdInput] = useState("");
  const [selectedOrderId, setSelectedOrderId] = useState("");
  const [search, setSearch] = useState<Slice<SalesOrderList>>(empty());
  const [detail, setDetail] = useState<Slice<SalesOrderDetail>>(empty());
  const [deliveries, setDeliveries] = useState<Slice<DeliveryList>>(empty());
  const [billings, setBillings] = useState<Slice<BillingList>>(empty());
  const clientRef = useRef<ODataClient | null>(null);
  const handlersRef = useRef<Record<Operation, (args: any) => Promise<any>>>({} as Record<Operation, (args: any) => Promise<any>>);

  useEffect(() => { void loadRuntime().then((loaded) => { clientRef.current = new ODataClient(loaded.config, loaded.bindings); setRuntime(loaded); }).catch((error) => setBootError(error instanceof Error ? error.message : "runtime 設定載入失敗。")); }, []);

  useEffect(() => {
    if (!runtime) return;
    const context = (document as Document & { modelContext?: ModelContext }).modelContext;
    if (!context) { setRegistration("unavailable"); return; }
    let controller: AbortController | null = null;
    setRegistration("loading");
    void registerConditionTools(context, runtime.catalog, {
      search_sales_orders: (args: any) => handlersRef.current.search_sales_orders(args),
      get_sales_order: (args: any) => handlersRef.current.get_sales_order(args),
      get_related_deliveries: (args: any) => handlersRef.current.get_related_deliveries(args),
      get_related_billing_documents: (args: any) => handlersRef.current.get_related_billing_documents(args),
    }).then((registered: AbortController) => { controller = registered; setRegistration("ready"); }).catch(() => setRegistration("error"));
    return () => controller?.abort();
  }, [runtime]);

  async function invoke<T>(operation: Operation, args: any, setSlice: (next: Slice<T>) => void): Promise<T> {
    const client = clientRef.current;
    if (!client) throw new Error("SAP runtime 尚未準備完成。");
    setSlice({ loading: true, data: null, error: "" });
    try {
      const result = await ({
        search_sales_orders: () => client.searchSalesOrders(args),
        get_sales_order: () => client.getSalesOrder(args),
        get_related_deliveries: () => client.getRelatedDeliveries(args),
        get_related_billing_documents: () => client.getRelatedBillingDocuments(args),
      }[operation]() as Promise<T>);
      setSlice({ loading: false, data: result, error: "" });
      return result;
    } catch (error) {
      const message = error instanceof ActionFailure ? error.detail.message : error instanceof Error ? error.message : "查詢失敗。";
      setSlice({ loading: false, data: null, error: message });
      throw error;
    }
  }

  handlersRef.current = {
    search_sales_orders: (args) => invoke("search_sales_orders", args, setSearch),
    get_sales_order: async (args) => {
      const id = String(args.sales_order_id ?? "").trim();
      setSelectedOrderId(id);
      setDeliveries(empty()); setBillings(empty());
      return invoke("get_sales_order", args, setDetail);
    },
    get_related_deliveries: async (args) => {
      const id = String(args.sales_order_id ?? "").trim();
      if (id && id !== selectedOrderId) { setSelectedOrderId(id); setDetail(empty()); setBillings(empty()); }
      return invoke("get_related_deliveries", args, setDeliveries);
    },
    get_related_billing_documents: async (args) => {
      const id = String(args.sales_order_id ?? "").trim();
      if (id && id !== selectedOrderId) { setSelectedOrderId(id); setDetail(empty()); setDeliveries(empty()); }
      return invoke("get_related_billing_documents", args, setBillings);
    },
  };

  function criteriaChange(key: keyof CanonicalCriteria, value: string) { setCriteria((current) => ({ ...current, [key]: value || undefined })); }
  async function submitSearch(event: React.FormEvent) { event.preventDefault(); setSelectedOrderId(""); setDetail(empty()); setDeliveries(empty()); setBillings(empty()); await handlersRef.current.search_sales_orders({ criteria }); }
  async function directLookup(event: React.FormEvent) { event.preventDefault(); await handlersRef.current.get_sales_order({ sales_order_id: orderIdInput }); }
  function selectOrder(id: string) { setOrderIdInput(id); void handlersRef.current.get_sales_order({ sales_order_id: id }); }

  const statusText = registration === "ready" ? "WebMCP 已註冊四個工具" : registration === "unavailable" ? "目前瀏覽器未提供 WebMCP" : registration === "error" ? "WebMCP 註冊失敗" : "WebMCP 註冊中";
  return <main className="app-shell">
    <aside className="status-rail" aria-label="系統狀態">
      <div className="brand"><p className="eyebrow">SAP SD / WebMCP</p><h1>跨文件查詢</h1><p>瀏覽器直連的唯讀研究原型</p></div>
      <div className="rail-stack">
        <div className={`rail-status ${registration === "ready" ? "is-ok" : registration === "error" ? "is-error" : ""}`}><Database size={16} /><div><strong>WebMCP</strong><span>{statusText}</span></div></div>
        <div className="rail-status"><ShieldCheck size={16} /><div><strong>執行政策</strong><span>HTTP GET only</span><span>OData V2 / no fallback</span></div></div>
        <div className="rail-status"><Server size={16} /><div><strong>SAP OData</strong><span>{runtime ? "已載入受治理設定" : "等待 runtime 設定"}</span></div></div>
      </div>
      <p className="rail-note">Agent 對話在 ChatGPT／Codex 中進行；此頁只提供共看的工作台與工具。</p>
    </aside>
    <section className="workspace">
      <header className="workspace-header"><div><p className="eyebrow">SAP Sales & Distribution</p><h2>銷售訂單文件流工作台</h2><p>以相同的瀏覽器執行層查詢銷售訂單、外向交貨與請款文件。</p></div><div className="header-badges"><span className="policy-badge"><ShieldCheck size={15} />唯讀</span><span className="policy-badge"><Database size={15} />OData V2</span></div></header>
      {bootError ? <ErrorBox message={bootError} /> : null}
      <section className="search-toolbar panel">
        <div className="panel-heading"><div><h3>查詢銷售訂單</h3><p>條件會轉換成受治理的 OData V2 filter；不接受未列入 allowlist 的欄位。</p></div></div>
        <div className="query-grid">
          <form className="direct-form" onSubmit={(event) => void directLookup(event)}><label>訂單編號<input value={orderIdInput} onChange={(event) => setOrderIdInput(event.target.value)} placeholder="例如 100001" maxLength={10} /></label><button className="primary-button" type="submit" disabled={!runtime || detail.loading}><Search size={16} />直接查詢</button></form>
          <form className="criteria-form" onSubmit={(event) => void submitSearch(event)}><label>客戶識別碼<input value={criteria.customer_id ?? ""} onChange={(event) => criteriaChange("customer_id", event.target.value)} maxLength={10} /></label><label>訂單日期起<input type="date" value={criteria.order_date_from ?? ""} onChange={(event) => criteriaChange("order_date_from", event.target.value)} /></label><label>訂單日期迄<input type="date" value={criteria.order_date_to ?? ""} onChange={(event) => criteriaChange("order_date_to", event.target.value)} /></label><label>訂單狀態<select value={criteria.order_status ?? ""} onChange={(event) => criteriaChange("order_status", event.target.value)}><option value="">不限</option><option value="not_started">尚未開始</option><option value="partially_completed">部分完成</option><option value="completed">已完成</option></select></label><button className="secondary-button" type="submit" disabled={!runtime || search.loading}><Search size={16} />條件搜尋</button></form>
        </div>
      </section>
      <div className="top-grid"><SearchResults result={search} selected={selectedOrderId} onSelect={selectOrder} /><OrderSummary result={detail} selectedId={selectedOrderId} /></div>
      <section className="panel flow-panel"><div className="panel-heading"><div><h3>文件流程</h3><p>每個 downstream 分支獨立查詢，避免頁面替 Agent 固定工具順序。</p></div>{selectedOrderId ? <span className="selected-tag">訂單 {selectedOrderId}</span> : null}</div>{selectedOrderId ? <div className="flow-grid"><FlowCard icon={<Truck size={18} />} title="外向交貨" state={deliveries} onLoad={() => void handlersRef.current.get_related_deliveries({ sales_order_id: selectedOrderId })}>{deliveries.data?.items.map((item) => <FlowRow key={item.delivery_id} id={item.delivery_id} date={item.delivery_date} status={item.delivery_status} />)}</FlowCard><FlowCard icon={<ReceiptText size={18} />} title="請款文件" state={billings} onLoad={() => void handlersRef.current.get_related_billing_documents({ sales_order_id: selectedOrderId })}>{billings.data?.items.map((item) => <FlowRow key={item.billing_document_id} id={item.billing_document_id} date={item.billing_date} status={item.billing_status} />)}</FlowCard></div> : <Empty message="請先直接查詢或選取一筆銷售訂單。" />}</section>
      <footer className="provenance"><span>{runtime ? `Model ${runtime.bindings.model.id} / ${runtime.bindings.model.version}` : "Model 尚未載入"}</span><span>{runtime?.config.transport === "local-gateway" ? "Transport: localhost Gateway" : "Transport: browser direct"}</span><span>結果只保留在目前瀏覽器頁面記憶體</span></footer>
    </section>
  </main>;
}

function SearchResults({ result, selected, onSelect }: { result: Slice<SalesOrderList>; selected: string; onSelect: (id: string) => void }) { return <section className="panel results-panel"><div className="panel-heading"><div><h3>搜尋結果</h3><p>{result.data ? `本次正規化 ${result.data.count} 筆` : "尚未執行條件搜尋"}</p></div></div>{result.loading ? <Loading label="正在讀取銷售訂單…" /> : result.error ? <ErrorBox message={result.error} /> : result.data?.items.length ? <div className="table-scroll"><table><thead><tr><th>訂單</th><th>客戶</th><th>訂單日期</th><th>狀態</th><th aria-label="操作" /></tr></thead><tbody>{result.data.items.map((item) => <tr className={item.sales_order_id === selected ? "is-selected" : ""} key={item.sales_order_id}><td><button className="row-link" type="button" onClick={() => onSelect(item.sales_order_id)}>{item.sales_order_id}<ChevronRight size={14} /></button></td><td>{item.customer_id ?? "—"}</td><td>{formatDate(item.order_date)}</td><td><StatusPill value={item.order_status} /></td><td><button className="text-button" type="button" onClick={() => onSelect(item.sales_order_id)}>選取</button></td></tr>)}</tbody></table></div> : <Empty message="沒有符合條件的銷售訂單。" />}</section>; }
function OrderSummary({ result, selectedId }: { result: Slice<SalesOrderDetail>; selectedId: string }) { const item = result.data?.sales_order; return <section className="panel summary-panel"><div className="panel-heading"><div><h3>目前選取訂單</h3><p>{selectedId ? `Sales Order ${selectedId}` : "尚未選取"}</p></div></div>{result.loading ? <Loading label="正在讀取訂單明細…" /> : result.error ? <ErrorBox message={result.error} /> : item ? <div className="summary-grid"><div><span>訂單識別碼</span><strong>{item.sales_order_id}</strong></div><div><span>客戶</span><strong>{item.customer_id ?? "—"}</strong></div><div><span>訂單日期</span><strong>{formatDate(item.order_date)}</strong></div><div><span>訂單狀態</span><StatusPill value={item.order_status} /></div></div> : <Empty message={selectedId ? "查無此訂單。" : "請從結果選取訂單，或使用上方直接查詢。"} />}</section>; }
function FlowCard({ icon, title, state, onLoad, children }: { icon: React.ReactNode; title: string; state: Slice<any>; onLoad: () => void; children: React.ReactNode }) { return <article className="flow-card"><div className="flow-card-heading"><div className="flow-icon">{icon}</div><div><h4>{title}</h4><p>{state.data ? `本次 ${state.data.count} 筆` : "尚未查詢"}</p></div><button className="text-button" type="button" onClick={onLoad} disabled={state.loading}>{state.loading ? "查詢中" : "載入"}</button></div>{state.error ? <ErrorBox message={state.error} onRetry={onLoad} /> : state.loading ? <Loading label={`正在讀取${title}…`} /> : state.data?.items.length ? <div className="flow-rows">{children}</div> : <Empty message={state.data ? `沒有相關${title}。` : `按「載入」查詢${title}。`} />}</article>; }
function FlowRow({ id, date, status }: { id: string; date: string | null; status: string | null }) { return <div className="flow-row"><div><strong>{id}</strong><span>{formatDate(date)}</span></div><StatusPill value={status} /></div>; }

export default App;
