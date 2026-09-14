import { readFile } from "node:fs/promises";
import { registerConditionTools } from "../prototype/webmcp/register-semantic-tools.mjs";

const artifactPaths = process.argv.slice(2);
if (artifactPaths.length === 0) throw new Error("usage: node scripts/smoke_webmcp_registration.mjs <catalog.json> [...catalog.json]");
const registered = [];
const modelContext = {
  async registerTool(tool, options) {
    if (tool.outputSchema !== undefined) throw new Error("outputSchema must stay in the research catalog");
    if (tool.operationId !== undefined) throw new Error("operationId must stay in the research catalog");
    if (tool.annotations?.readOnlyHint !== true) throw new Error("readOnlyHint must be true");
    if (!options?.signal) throw new Error("registration must be abortable");
    registered.push(tool);
  },
};
for (const artifactPath of artifactPaths) {
  const catalog = JSON.parse(await readFile(artifactPath, "utf8"));
  const start = registered.length;
  const actions = Object.fromEntries(
    catalog.tools.map((tool) => [tool.operationId, async (args) => ({ operationId: tool.operationId, args })]),
  );
  const controller = await registerConditionTools(modelContext, catalog, actions);
  if (controller.signal.aborted) throw new Error("registration signal unexpectedly aborted");
  const tools = registered.slice(start);
  if (tools.length !== 4) throw new Error(`expected 4 tools, got ${tools.length}`);
  for (const tool of tools) {
    if (!tool.inputSchema || typeof tool.inputSchema !== "object") throw new Error(`${tool.name} has no input schema`);
    if (typeof tool.inputSchema.properties !== "object") throw new Error(`${tool.name} has no properties`);
  }
  for (const tool of tools) {
    const isSearch = Object.hasOwn(tool.inputSchema.properties, "filter") || Object.hasOwn(tool.inputSchema.properties, "criteria");
    const sample = catalog.condition === "A"
      ? (isSearch ? { filter: { SoldToParty: "CUST01" } } : { SalesOrder: "100001" })
      : (isSearch ? { criteria: { customer_id: "CUST01" } } : { sales_order_id: "100001" });
    const result = await tool.execute(sample);
    if (isSearch) {
      if (result.args.criteria?.customer_id !== "CUST01") throw new Error(`${tool.name} did not canonicalize search criteria`);
    } else if (result.args.sales_order_id !== "100001") {
      throw new Error(`${tool.name} did not canonicalize SalesOrder`);
    }
  }
}
console.log(JSON.stringify({ok: true, registered: registered.map((tool) => tool.name)}));
