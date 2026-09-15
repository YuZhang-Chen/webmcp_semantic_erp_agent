declare module "*.mjs" {
  export function registerConditionTools(
    modelContext: unknown,
    catalog: unknown,
    actions: Record<string, (args: unknown) => Promise<unknown>>,
    observer?: unknown,
  ): Promise<AbortController>;
}
