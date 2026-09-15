import type { ActionError, ExperimentContext, PageStateSnapshot } from "./types";

type ToolToken = {
  callOrder: number;
  toolName: string;
  operationId: string;
  publicParameters: unknown;
  canonicalParameters?: unknown;
  before: PageStateSnapshot;
  startedAt: number;
};

function errorDetail(error: unknown): { code: string; message: string; retryable: boolean; category: "parameter_error" | "sap_query_error" } {
  const detail = (error as { detail?: ActionError })?.detail;
  if (detail) {
    return {
      code: detail.code,
      message: detail.message,
      retryable: detail.retryable,
      category: detail.code === "ARGUMENT_INVALID" ? "parameter_error" : "sap_query_error",
    };
  }
  return {
    code: error instanceof TypeError ? "ARGUMENT_INVALID" : "EXECUTION_FAILED",
    message: error instanceof Error ? error.message : "工具執行失敗。",
    retryable: false,
    category: error instanceof TypeError ? "parameter_error" : "sap_query_error",
  };
}

function resultSummary(result: any): Record<string, unknown> {
  if (Array.isArray(result?.items)) {
    return {
      count: Number(result.count ?? result.items.length),
      items: result.items.map((item: Record<string, unknown>) => ({
        sales_order_id: item.sales_order_id,
        delivery_id: item.delivery_id,
        billing_document_id: item.billing_document_id,
        order_status: item.order_status,
        delivery_status: item.delivery_status,
        billing_status: item.billing_status,
      })),
      request_id: result.trace?.request_id,
    };
  }
  if (result?.sales_order !== undefined) {
    return { sales_order: result.sales_order, request_id: result.trace?.request_id };
  }
  return { kind: "unknown" };
}

export class ExperimentLogger {
  private sequence = 0;
  private callOrder = 0;
  private queue: Promise<void> = Promise.resolve();

  constructor(private readonly context: ExperimentContext, private readonly snapshot: () => PageStateSnapshot) {}

  start(): Promise<void> {
    return this.emit({ event_type: "run_started", actor: "system" });
  }

  started(toolName: string, operationId: string, publicParameters: unknown): ToolToken {
    return {
      callOrder: ++this.callOrder,
      toolName,
      operationId,
      publicParameters,
      before: this.snapshot(),
      startedAt: performance.now(),
    };
  }

  canonicalized(token: ToolToken, parameters: unknown): void {
    token.canonicalParameters = parameters;
  }

  async finished(token: ToolToken, success: boolean, result?: unknown, error?: unknown): Promise<void> {
    const failure = success ? null : errorDetail(error);
    await this.emit({
      event_type: "tool_call",
      actor: "agent",
      call_order: token.callOrder,
      tool_name: token.toolName,
      canonical_operation: token.operationId,
      parameters: token.canonicalParameters ?? token.publicParameters,
      success,
      duration_ms: Math.max(0, Math.round(performance.now() - token.startedAt)),
      result_summary: success ? resultSummary(result) : null,
      error: failure ? { code: failure.code, message: failure.message, retryable: failure.retryable } : null,
      error_category: failure?.category ?? null,
      page_state_before: token.before,
      page_state_after: this.snapshot(),
    });
  }

  private emit(payload: Record<string, unknown>): Promise<void> {
    const event = {
      schema_version: "1.0",
      run_id: this.context.run_id,
      task_id: this.context.task_id,
      condition: this.context.condition,
      repetition: this.context.repetition,
      sequence: ++this.sequence,
      timestamp: new Date().toISOString(),
      ...payload,
    };
    this.queue = this.queue.then(async () => {
      const response = await fetch(this.context.endpoint, {
        method: "POST",
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(event),
      });
      if (!response.ok) throw new Error(`execution logger failed (HTTP ${response.status})`);
    });
    return this.queue;
  }
}
