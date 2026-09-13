import { readFile } from "node:fs/promises";
import { registerSemanticTools } from "../prototype/webmcp/register-semantic-tools.mjs";

const artifactPath = process.argv[2];
if (!artifactPath) throw new Error("usage: node scripts/smoke_webmcp_registration.mjs <catalog.json>");
const catalog = JSON.parse(await readFile(artifactPath, "utf8"));
const registered = [];
const modelContext = {
  async registerTool(tool, options) {
    if (tool.outputSchema !== undefined) throw new Error("outputSchema must stay in the research catalog");
    if (tool.annotations?.readOnlyHint !== true) throw new Error("readOnlyHint must be true");
    if (!options?.signal) throw new Error("registration must be abortable");
    registered.push(tool);
  },
};
const actions = Object.fromEntries(
  catalog.tools.map((tool) => [tool.operationId, async (args) => ({ operationId: tool.operationId, args })]),
);
const controller = await registerSemanticTools(modelContext, catalog, actions);
if (registered.length !== 4) throw new Error(`expected 4 tools, got ${registered.length}`);
if (controller.signal.aborted) throw new Error("registration signal unexpectedly aborted");
for (const tool of registered) {
  if (!tool.inputSchema || typeof tool.inputSchema !== "object") throw new Error(`${tool.name} has no input schema`);
  if (typeof tool.inputSchema.properties !== "object") throw new Error(`${tool.name} has no properties`);
  const result = await tool.execute({sales_order_id: "100001"});
  if (result.operationId !== tool.name) throw new Error(`${tool.name} routed to the wrong action`);
}
console.log(JSON.stringify({ok: true, registered: registered.map((tool) => tool.name)}));
