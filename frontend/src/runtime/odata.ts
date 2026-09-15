import type {
  ActionError,
  BillingList,
  CanonicalCriteria,
  DeliveryList,
  RuntimeArtifact,
  RuntimeBinding,
  RuntimeConfig,
  SalesOrderDetail,
  SalesOrderList,
  SalesOrderSummary,
  Trace,
} from "./types";

const OPERATIONS = new Set(["search_sales_orders", "get_sales_order", "get_related_deliveries", "get_related_billing_documents"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export class ActionFailure extends Error {
  readonly detail: ActionError;
  constructor(detail: ActionError) {
    super(detail.message);
    this.name = "ActionFailure";
    this.detail = detail;
  }
}

function fail(code: string, message: string, requestId: string, operationId: string, retryable = false): never {
  throw new ActionFailure({ code, message, request_id: requestId, operation_id: operationId, retryable });
}

function requireString(value: unknown, field: string, requestId: string, operationId: string, max = 10): string {
  if (typeof value !== "string" || value.trim().length === 0 || value.trim().length > max) {
    fail("ARGUMENT_INVALID", `${field} 格式不正確。`, requestId, operationId);
  }
  return value.trim();
}

function validateCriteria(criteria: unknown, requestId: string, operationId: string): CanonicalCriteria {
  if (!criteria || typeof criteria !== "object" || Array.isArray(criteria)) fail("ARGUMENT_INVALID", "搜尋條件格式不正確。", requestId, operationId);
  const source = criteria as Record<string, unknown>;
  const allowed = new Set(["customer_id", "order_date_from", "order_date_to", "order_status"]);
  if (Object.keys(source).some((key) => !allowed.has(key)) || Object.keys(source).length === 0) fail("ARGUMENT_INVALID", "搜尋條件不在 allowlist 內。", requestId, operationId);
  const result: CanonicalCriteria = {};
  if (source.customer_id !== undefined) result.customer_id = requireString(source.customer_id, "customer_id", requestId, operationId);
  if (source.order_date_from !== undefined) {
    if (typeof source.order_date_from !== "string" || !ISO_DATE.test(source.order_date_from)) fail("ARGUMENT_INVALID", "起始日期格式不正確。", requestId, operationId);
    result.order_date_from = source.order_date_from;
  }
  if (source.order_date_to !== undefined) {
    if (typeof source.order_date_to !== "string" || !ISO_DATE.test(source.order_date_to)) fail("ARGUMENT_INVALID", "結束日期格式不正確。", requestId, operationId);
    result.order_date_to = source.order_date_to;
  }
  if (result.order_date_from && result.order_date_to && result.order_date_from > result.order_date_to) fail("ARGUMENT_INVALID", "起始日期不可晚於結束日期。", requestId, operationId);
  if (source.order_status !== undefined) {
    if (!["not_started", "partially_completed", "completed"].includes(String(source.order_status))) fail("ARGUMENT_INVALID", "訂單狀態不在受治理清單內。", requestId, operationId);
    result.order_status = source.order_status as CanonicalCriteria["order_status"];
  }
  return result;
}

function escapeLiteral(value: string): string { return `'${value.replaceAll("'", "''")}'`; }
function dateLiteral(value: string, end = false): string { return `datetime'${value}T${end ? "23:59:59" : "00:00:00"}'`; }

function normalizedDate(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") return null;
  const sap = value.match(/^\/Date\((\d+)(?:[+-]\d+)?\)\/$/);
  if (sap) return new Date(Number(sap[1])).toISOString().slice(0, 10);
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value.slice(0, 10) : parsed.toISOString().slice(0, 10);
}

function mappedCode(value: unknown, map: Record<string, string> | undefined): string | null {
  if (value === null || value === undefined || value === "") return map?.[""] ?? null;
  return map?.[String(value)] ?? null;
}

function trace(operationId: string, model: RuntimeArtifact["model"], evidenceId: string, requestId: string): Trace {
  return { request_id: requestId, operation_id: operationId, model_id: "sap-sd-webmcp", model_version: model.version, protocol: "odata-v2", retrieved_at: new Date().toISOString(), source_evidence_id: evidenceId };
}

export class ODataClient {
  constructor(private readonly config: RuntimeConfig, private readonly artifact: RuntimeArtifact) {}

  async searchSalesOrders(args: { criteria: unknown }): Promise<SalesOrderList> {
    const operationId = "search_sales_orders";
    const requestId = crypto.randomUUID();
    const criteria = validateCriteria(args?.criteria, requestId, operationId);
    const { binding } = this.operation(operationId);
    const filters = this.criteriaFilters(criteria, binding, requestId, operationId);
    const rows = await this.collection(binding, filters, this.select(binding, false), requestId, operationId);
    const items = rows.map((row) => this.salesOrder(row, binding, requestId, operationId));
    return { items, count: items.length, trace: trace(operationId, this.artifact.model, binding.source_evidence_id, requestId) };
  }

  async getSalesOrder(args: { sales_order_id: unknown }): Promise<SalesOrderDetail> {
    const operationId = "get_sales_order";
    const requestId = crypto.randomUUID();
    const id = requireString(args?.sales_order_id, "sales_order_id", requestId, operationId);
    const { binding } = this.operation(operationId);
    const rows = await this.collection(binding, [`${this.field(binding, "sales_order_id")} eq ${escapeLiteral(id)}`], this.select(binding, false), requestId, operationId, 2);
    if (rows.length > 1) fail("RESULT_NOT_UNIQUE", "銷售訂單識別碼不是唯一結果。", requestId, operationId);
    return { sales_order: rows.length ? this.salesOrder(rows[0], binding, requestId, operationId) : null, trace: trace(operationId, this.artifact.model, binding.source_evidence_id, requestId) };
  }

  async getRelatedDeliveries(args: { sales_order_id: unknown }): Promise<DeliveryList> {
    return await this.related(args, "get_related_deliveries", "delivery") as DeliveryList;
  }

  async getRelatedBillingDocuments(args: { sales_order_id: unknown }): Promise<BillingList> {
    return await this.related(args, "get_related_billing_documents", "billing") as BillingList;
  }

  private async related(args: { sales_order_id: unknown }, operationId: "get_related_deliveries" | "get_related_billing_documents", kind: "delivery" | "billing"): Promise<DeliveryList | BillingList> {
    const requestId = crypto.randomUUID();
    const id = requireString(args?.sales_order_id, "sales_order_id", requestId, operationId);
    const { binding } = this.operation(operationId);
    const discriminator = binding.discriminator;
    const category = Object.entries(discriminator?.code_map ?? {}).find(([, business]) => business === (kind === "delivery" ? "outbound_delivery" : "billing_document"))?.[0];
    if (!discriminator?.property || !category) fail("POLICY_VIOLATION", "文件流 discriminator 未完成治理。", requestId, operationId);
    const rows = await this.collection(binding, [`${this.field(binding, "sales_order_id")} eq ${escapeLiteral(id)}`, `${discriminator.property} eq ${escapeLiteral(category)}`], this.select(binding, true), requestId, operationId);
    const enrichment = binding.enrichment;
    if (!enrichment) fail("POLICY_VIOLATION", "文件流 enrichment 未完成治理。", requestId, operationId);
    const items = [] as Array<Record<string, unknown>>;
    for (const row of rows) {
      const documentId = String(row[this.field(binding, kind === "delivery" ? "delivery_id" : "billing_document_id")] ?? "").trim();
      if (!documentId) fail("ODATA_SHAPE_INVALID", "SAP 文件流回應缺少文件識別碼。", requestId, operationId);
      const enriched = await this.uniqueEnrichment(enrichment, documentId, requestId, operationId);
      if (kind === "delivery") {
        items.push({ delivery_id: documentId, sales_order_id: id, delivery_date: normalizedDate(enriched?.[this.enrichmentField(binding, "delivery_date")]), delivery_status: mappedCode(enriched?.[this.enrichmentField(binding, "delivery_status")], this.enrichmentMap(binding, "delivery_status")) });
      } else {
        items.push({ billing_document_id: documentId, sales_order_id: id, billing_date: normalizedDate(enriched?.[this.enrichmentField(binding, "billing_date")]), billing_status: mappedCode(enriched?.[this.enrichmentField(binding, "billing_status")], this.enrichmentMap(binding, "billing_status")) });
      }
    }
    const output = { items, count: items.length, trace: trace(operationId, this.artifact.model, binding.source_evidence_id, requestId) };
    return output as DeliveryList | BillingList;
  }

  private operation(operationId: string): { binding: RuntimeBinding } & { output: Record<string, unknown> } {
    if (!OPERATIONS.has(operationId)) throw new Error("unsupported operation");
    const operation = this.artifact.operations[operationId];
    if (!operation) throw new Error("runtime operation is missing");
    return { binding: operation.binding, output: operation.outputSchema };
  }

  private field(binding: RuntimeBinding, name: string): string {
    const field = binding.parameters[name] ?? binding.output_fields[name];
    if (!field?.property) throw new Error(`runtime field missing: ${name}`);
    return field.property;
  }

  private select(binding: RuntimeBinding, includeDiscriminator: boolean): string {
    const properties = new Set(Object.values(binding.output_fields).filter((field) => field.step_ref !== "enrichment").map((field) => field.property));
    if (includeDiscriminator && binding.discriminator?.property) properties.add(binding.discriminator.property);
    return Array.from(properties).join(",");
  }

  private criteriaFilters(criteria: CanonicalCriteria, binding: RuntimeBinding, requestId: string, operationId: string): string[] {
    const filters: string[] = [];
    if (criteria.customer_id) filters.push(`${this.field(binding, "customer_id")} eq ${escapeLiteral(criteria.customer_id)}`);
    if (criteria.order_date_from) filters.push(`${this.field(binding, "order_date_from")} ge ${dateLiteral(criteria.order_date_from)}`);
    if (criteria.order_date_to) filters.push(`${this.field(binding, "order_date_to")} le ${dateLiteral(criteria.order_date_to, true)}`);
    if (criteria.order_status) {
      const code = Object.entries(binding.parameters.order_status?.code_map ?? {}).find(([, business]) => business === criteria.order_status)?.[0];
      if (!code) fail("POLICY_VIOLATION", "訂單狀態缺少受治理 code mapping。", requestId, operationId);
      filters.push(`${this.field(binding, "order_status")} eq ${escapeLiteral(code)}`);
    }
    return filters;
  }

  private async collection(binding: RuntimeBinding, filters: string[], select: string, requestId: string, operationId: string, top = this.artifact.policy.maxRows): Promise<Array<Record<string, unknown>>> {
    if (binding.method !== "GET") fail("POLICY_VIOLATION", "SAP runtime 僅允許 GET。", requestId, operationId);
    const service = this.config.services[binding.service_id];
    if (!service) fail("CONFIG_INVALID", "缺少受允許的 SAP service 設定。", requestId, operationId);
    let url = this.endpoint(service, binding.entity_set);
    const rows: Array<Record<string, unknown>> = [];
    while (rows.length < top) {
      const params = new URLSearchParams({ "$select": select, "$top": String(Math.min(top - rows.length, this.artifact.policy.maxRows)), "$format": "json" });
      if (filters.length) params.set("$filter", filters.join(" and "));
      if (this.config.client) params.set("sap-client", this.config.client);
      if (this.config.language) params.set("sap-language", this.config.language);
      const payload = await this.getJson(url, params, requestId, operationId);
      const data = payload.d;
      if (!data || !Array.isArray(data.results)) fail("ODATA_SHAPE_INVALID", "SAP OData V2 collection 回應格式不正確。", requestId, operationId);
      rows.push(...data.results);
      const next = data.__next;
      if (!next || rows.length >= top) break;
      const nextUrl = this.nextUrl(next, service, requestId, operationId);
      url = nextUrl;
      filters = [];
    }
    return rows.slice(0, top);
  }

  private async uniqueEnrichment(enrichment: NonNullable<RuntimeBinding["enrichment"]>, id: string, requestId: string, operationId: string): Promise<Record<string, unknown> | null> {
    const service = this.config.services[enrichment.service_id];
    if (!service) fail("CONFIG_INVALID", "缺少 enrichment service 設定。", requestId, operationId);
    const url = this.endpoint(service, enrichment.entity_set);
    const params = new URLSearchParams({ "$filter": `${enrichment.key_property} eq ${escapeLiteral(id)}`, "$select": this.enrichmentSelect(enrichment, operationId), "$top": "2", "$format": "json" });
    if (this.config.client) params.set("sap-client", this.config.client);
    if (this.config.language) params.set("sap-language", this.config.language);
    const payload = await this.getJson(url, params, requestId, operationId);
    if (!payload.d || !Array.isArray(payload.d.results)) fail("ODATA_SHAPE_INVALID", "SAP enrichment 回應格式不正確。", requestId, operationId);
    if (payload.d.results.length > 1) fail("RESULT_NOT_UNIQUE", "下游文件識別碼不是唯一結果。", requestId, operationId);
    return payload.d.results[0] ?? null;
  }

  private enrichmentSelect(enrichment: NonNullable<RuntimeBinding["enrichment"]>, operationId: string): string {
    const fields = this.artifact.operations[operationId].binding.output_fields;
    const selected = Object.values(fields).filter((field) => field.step_ref === "enrichment").map((field) => field.property);
    return Array.from(new Set([enrichment.key_property, ...selected])).join(",");
  }

  private enrichmentField(binding: RuntimeBinding, fieldId: string): string {
    const field = binding.output_fields[fieldId];
    if (!field?.property) throw new Error(`enrichment field missing: ${fieldId}`);
    return field.property;
  }

  private enrichmentMap(binding: RuntimeBinding, fieldId: string): Record<string, string> | undefined { return binding.output_fields[fieldId]?.code_map; }

  private salesOrder(row: Record<string, unknown>, binding: RuntimeBinding, requestId: string, operationId: string): SalesOrderSummary {
    const id = String(row[this.field(binding, "sales_order_id")] ?? "").trim();
    if (!id) fail("ODATA_SHAPE_INVALID", "SAP 回應缺少銷售訂單識別碼。", requestId, operationId);
    return { sales_order_id: id, customer_id: row[this.field(binding, "customer_id")] == null ? null : String(row[this.field(binding, "customer_id")]), order_date: normalizedDate(row[this.field(binding, "order_date")]), order_status: mappedCode(row[this.field(binding, "order_status")], binding.output_fields.order_status?.code_map) as SalesOrderSummary["order_status"] };
  }

  private endpoint(service: string, entitySet: string): string {
    if (this.config.transport === "local-gateway") {
      const serviceId = Object.entries(this.config.services).find(([, value]) => value === service)?.[0];
      if (!serviceId || !this.config.gateway_base_path) throw new Error("gateway service policy violation");
      if (!/^[A-Za-z0-9_]+$/.test(entitySet)) throw new Error("entity set policy violation");
      return `${this.config.gateway_base_path}/${serviceId}/${entitySet}`;
    }
    const base = new URL(service);
    if (base.protocol !== "https:" || base.username || base.password || base.search || base.hash) throw new Error("service URL policy violation");
    return new URL(`${entitySet.replace(/^\//, "")}`, service.endsWith("/") ? service : `${service}/`).toString();
  }

  private nextUrl(candidate: string, service: string, requestId: string, operationId: string): string {
    try {
      if (this.config.transport === "local-gateway") {
        const expected = `${service}/__next/`;
        if (!candidate.startsWith(expected)) fail("PAGINATION_INVALID", "SAP 分頁連結不在受允許的 gateway service root。", requestId, operationId);
        return new URL(candidate, window.location.origin).toString();
      }
      const next = new URL(candidate, service);
      const root = new URL(service);
      if (next.protocol !== "https:" || next.origin !== root.origin || !next.pathname.startsWith(root.pathname)) fail("PAGINATION_INVALID", "SAP 分頁連結不在受允許的 service root。", requestId, operationId);
      return next.toString();
    } catch (error) {
      if (error instanceof ActionFailure) throw error;
      fail("PAGINATION_INVALID", "SAP 分頁連結格式不正確。", requestId, operationId);
    }
  }

  private async getJson(url: string, params: URLSearchParams, requestId: string, operationId: string): Promise<{ d: { results?: Array<Record<string, unknown>>; __next?: string } }> {
    const target = `${url}?${params.toString()}`;
    const bytes = new TextEncoder().encode(`${this.config.username ?? ""}:${this.config.password ?? ""}`);
    let binary = "";
    bytes.forEach((value) => { binary += String.fromCharCode(value); });
    try {
      const headers: Record<string, string> = { Accept: "application/json" };
      if (this.config.transport === "direct-browser") headers.Authorization = `Basic ${btoa(binary)}`;
      const response = await fetch(target, { method: "GET", mode: "cors", cache: "no-store", credentials: "omit", redirect: "error", headers });
      if (!response.ok) fail("SAP_REQUEST_FAILED", `SAP 查詢失敗（HTTP ${response.status}）。`, requestId, operationId, response.status >= 500);
      try { return await response.json() as { d: { results?: Array<Record<string, unknown>>; __next?: string } }; } catch { fail("ODATA_SHAPE_INVALID", "SAP 回應不是有效 JSON。", requestId, operationId); }
    } catch (error) {
      if (error instanceof ActionFailure) throw error;
      fail("SAP_REQUEST_FAILED", "SAP 連線失敗，請檢查 CORS、TLS 或驗證設定。", requestId, operationId, true);
    }
  }
}
