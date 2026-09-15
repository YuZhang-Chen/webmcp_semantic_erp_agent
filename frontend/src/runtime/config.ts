import type { RuntimeArtifact, RuntimeConfig, ToolCatalog } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "GET", cache: "no-store", credentials: "omit", redirect: "error" });
  if (!response.ok) throw new Error(`設定載入失敗（HTTP ${response.status}）`);
  try {
    return await response.json() as T;
  } catch {
    throw new Error("設定回應不是有效 JSON");
  }
}

export async function loadRuntime(): Promise<{ config: RuntimeConfig; catalog: ToolCatalog; bindings: RuntimeArtifact }> {
  const [config, catalog, bindings] = await Promise.all([
    getJson<RuntimeConfig>("/runtime/config.json"),
    getJson<ToolCatalog>("/runtime/tool-catalog.json"),
    getJson<RuntimeArtifact>("/runtime/bindings.json"),
  ]);
  if (catalog.tools.length !== 4 || bindings.protocol !== "odata-v2" || bindings.policy.fallback !== "forbidden" || !["direct-browser", "local-gateway"].includes(config.transport)) {
    throw new Error("Phase 06 runtime artifact 不符合受治理契約");
  }
  if (config.model.id !== bindings.model.id || config.model.version !== bindings.model.version) {
    throw new Error("runtime config 與 binding model 版本不一致");
  }
  return { config, catalog, bindings };
}
