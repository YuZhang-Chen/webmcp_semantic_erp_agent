/** Register a compiled C catalog against the page's WebMCP model context. */

export async function registerSemanticTools(modelContext, catalog, actions) {
  if (!modelContext || typeof modelContext.registerTool !== "function") {
    throw new TypeError("a WebMCP modelContext with registerTool() is required");
  }
  if (
    !catalog ||
    catalog.condition !== "C" ||
    !Array.isArray(catalog.tools) ||
    catalog.tools.length !== 4 ||
    typeof catalog.artifactSha256 !== "string"
  ) {
    throw new TypeError("an assembled C Semantic tool catalog is required");
  }

  const controller = new AbortController();
  try {
    for (const catalogTool of catalog.tools) {
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
          execute: (args) => action(args),
        },
        { signal: controller.signal },
      );
    }
  } catch (error) {
    controller.abort();
    throw error;
  }
  return controller;
}
