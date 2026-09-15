/** Register a Phase 05 condition catalog against the page's WebMCP model context. */

const CONDITIONS = new Set(["A", "B", "C"]);
const OPERATIONS = new Set([
  "search_sales_orders",
  "get_sales_order",
  "get_related_deliveries",
  "get_related_billing_documents",
]);

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

async function verifyArtifactHash(catalog) {
  if (typeof catalog?.artifactSha256 !== "string") return false;
  const unsigned = Object.fromEntries(Object.entries(catalog).filter(([key]) => key !== "artifactSha256"));
  const bytes = new TextEncoder().encode(stableStringify(unsigned));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const actual = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  return actual === catalog.artifactSha256;
}

export function canonicalizeArguments(condition, operationId, args) {
  if (!OPERATIONS.has(operationId)) throw new TypeError(`unsupported operation ${operationId}`);
  if (condition === "B" || condition === "C") {
    const expected = operationId === "search_sales_orders" ? ["criteria"] : ["sales_order_id"];
    if (!args || Object.keys(args).sort().join() !== expected.join()) throw new TypeError("invalid canonical arguments");
    if (operationId === "search_sales_orders") {
      const allowed = new Set(["customer_id", "order_date_from", "order_date_to", "order_status"]);
      if (!args.criteria || Object.keys(args.criteria).some((key) => !allowed.has(key))) throw new TypeError("invalid criteria");
    }
    return structuredClone(args);
  }
  if (condition !== "A" || !OPERATIONS.has(operationId)) {
    throw new TypeError(`unsupported condition or operation: ${condition}/${operationId}`);
  }
  if (operationId === "search_sales_orders") {
    if (!args || Object.keys(args).length !== 1 || !Object.hasOwn(args, "filter")) throw new TypeError("filter is required");
    const source = args?.filter ?? {};
    const allowed = new Set(["SoldToParty", "SalesOrderDate", "OverallSDProcessStatus"]);
    if (Object.keys(source).some((key) => !allowed.has(key))) throw new TypeError("unknown technical filter");
    const criteria = {};
    if (source.SoldToParty !== undefined) criteria.customer_id = source.SoldToParty;
    if (source.SalesOrderDate?.ge !== undefined) criteria.order_date_from = source.SalesOrderDate.ge;
    if (source.SalesOrderDate?.le !== undefined) criteria.order_date_to = source.SalesOrderDate.le;
    if (source.OverallSDProcessStatus !== undefined) {
      const status = { A: "not_started", B: "partially_completed", C: "completed" }[source.OverallSDProcessStatus];
      if (!status) throw new TypeError("unknown OverallSDProcessStatus");
      criteria.order_status = status;
    }
    return { criteria };
  }
  if (!args || Object.keys(args).length !== 1 || args.SalesOrder === undefined) throw new TypeError("SalesOrder is required");
  return { sales_order_id: args.SalesOrder };
}

export async function registerConditionTools(modelContext, catalog, actions) {
  if (!modelContext || typeof modelContext.registerTool !== "function") {
    throw new TypeError("a WebMCP modelContext with registerTool() is required");
  }
  if (
    !catalog ||
    !CONDITIONS.has(catalog.condition) ||
    !Array.isArray(catalog.tools) ||
    catalog.tools.length !== 4 ||
    !(await verifyArtifactHash(catalog))
  ) {
    throw new TypeError("an assembled A/B/C tool catalog is required");
  }

  const controller = new AbortController();
  try {
    const seenOperations = new Set();
    for (const catalogTool of catalog.tools) {
      if (!OPERATIONS.has(catalogTool.operationId)) {
        throw new TypeError(`unsupported operation ${catalogTool.operationId}`);
      }
      if (seenOperations.has(catalogTool.operationId)) {
        throw new TypeError(`duplicate operation ${catalogTool.operationId}`);
      }
      seenOperations.add(catalogTool.operationId);
      const action = actions?.[catalogTool.operationId];
      if (typeof action !== "function") {
        throw new TypeError(`missing action for ${catalogTool.operationId}`);
      }
      await modelContext.registerTool(
        {
          name: catalogTool.name,
          description: catalogTool.description,
          inputSchema: catalogTool.inputSchema,
          annotations: catalogTool.annotations,
          execute: (args) => action(canonicalizeArguments(catalog.condition, catalogTool.operationId, args)),
        },
        { signal: controller.signal },
      );
    }
    if (seenOperations.size !== OPERATIONS.size) throw new TypeError("catalog must contain all canonical operations");
  } catch (error) {
    controller.abort();
    throw error;
  }
  return controller;
}

export async function registerSemanticTools(modelContext, catalog, actions) {
  if (catalog?.condition !== "C") {
    throw new TypeError("an assembled C Semantic tool catalog is required");
  }
  return registerConditionTools(modelContext, catalog, actions);
}
