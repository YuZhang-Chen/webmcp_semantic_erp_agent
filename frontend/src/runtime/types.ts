export type Condition = "A" | "B" | "C";

export type LoadState<T> = {
  loading: boolean;
  data: T | null;
  error: string;
};

export type Trace = {
  request_id: string;
  operation_id: string;
  model_id: "sap-sd-webmcp";
  model_version: string;
  protocol: "odata-v2";
  retrieved_at: string;
  source_evidence_id: string;
};

export type SalesOrderSummary = {
  sales_order_id: string;
  customer_id: string | null;
  order_date: string | null;
  order_status: "not_started" | "partially_completed" | "completed" | null;
};

export type SalesOrderList = { items: SalesOrderSummary[]; count: number; trace: Trace };
export type SalesOrderDetail = { sales_order: SalesOrderSummary | null; trace: Trace };

export type DeliverySummary = {
  delivery_id: string;
  sales_order_id: string;
  delivery_date: string | null;
  delivery_status: "not_started" | "partially_completed" | "completed" | null;
};

export type BillingSummary = {
  billing_document_id: string;
  sales_order_id: string;
  billing_date: string | null;
  billing_status: "not_relevant" | "not_processed" | "partially_processed" | "completely_processed" | null;
};

export type DeliveryList = { items: DeliverySummary[]; count: number; trace: Trace };
export type BillingList = { items: BillingSummary[]; count: number; trace: Trace };

export type CanonicalCriteria = {
  customer_id?: string;
  order_date_from?: string;
  order_date_to?: string;
  order_status?: "not_started" | "partially_completed" | "completed";
};

export type RuntimeConfig = {
  model: { id: string; version: string };
  protocol: "odata-v2";
  transport: "direct-browser" | "local-gateway";
  gateway_base_path: string;
  username?: string;
  password?: string;
  client?: string;
  language?: string;
  services: Record<string, string>;
};

export type RuntimeArtifact = {
  schemaVersion: string;
  compilerVersion: string;
  model: { id: string; version: string; sha256: string; sourceId: string; modelSourceId: string };
  protocol: "odata-v2";
  policy: { allowedHttpMethods: ["GET"]; fallback: "forbidden"; maxRows: number };
  services: Record<string, { runtime_selector: string; protocol: "odata-v2" }>;
  operations: Record<string, { inputSchema: Record<string, unknown>; outputSchema: Record<string, unknown>; bindingRef: string; binding: RuntimeBinding }>;
  artifactSha256: string;
};

export type RuntimeBinding = {
  service_id: string;
  method: "GET";
  entity_set: string;
  query_strategy: "collection_filter" | "unique_filter";
  source_evidence_id: string;
  metadata_sha256: string;
  parameters: Record<string, RuntimeField>;
  output_fields: Record<string, RuntimeField>;
  discriminator?: RuntimeField | null;
  enrichment?: RuntimeEnrichment | null;
};

export type RuntimeField = {
  property: string;
  edm_type?: string;
  max_length?: number | null;
  code_map?: Record<string, string>;
  business_value?: string;
  step_ref?: string | null;
};

export type RuntimeEnrichment = {
  service_id: string;
  method: "GET";
  entity_set: string;
  query_strategy: "unique_filter";
  source_evidence_id: string;
  metadata_sha256: string;
  key_property: string;
  input_field: string;
  evidence_scope: "delivery" | "billing";
};

export type ToolCatalog = {
  schemaVersion: string;
  condition: Condition;
  compilerVersion: string;
  model: RuntimeArtifact["model"];
  tools: Array<{ operationId: string; name: string; description: string; inputSchema: Record<string, unknown>; annotations: { readOnlyHint: true }; outputSchema: Record<string, unknown> }>;
  artifactSha256: string;
};

export type ActionError = { code: string; message: string; request_id?: string; operation_id?: string; retryable: boolean };
