# Phase 5：A/B Baseline 與 C Semantic Tools

## 目的

建立可公平比較的三種工具介面，並把自變因限制為 Agent 所看到的語意增強程度。本階段完成契約、正規化與註冊原型；SAP OData 執行、網站狀態與 UI 留在 Phase 06。

## 固定控制變因

A、B、C 共用：

- 相同四個 canonical operations：`search_sales_orders`、`get_sales_order`、`get_related_deliveries`、`get_related_billing_documents`。
- 相同 `webmcp.sap_sd.odata` binding、輸入能力、輸出 schema、HTTP GET policy 與 browser-side action map。
- 相同頁面、prompt、任務、模型設定、評分與 logging 邊界。
- Agent 呼叫前，所有公開參數都先正規化成相同 canonical arguments。

任何 operation、輸出、action target 或輸入能力不一致，suite validation 都必須失敗。

## 三組條件

### A Technical Baseline

公開名稱與描述只呈現 SAP 技術介面：

| Canonical operation | A tool name |
| --- | --- |
| `search_sales_orders` | `query_A_SalesOrder` |
| `get_sales_order` | `read_A_SalesOrder` |
| `get_related_deliveries` | `query_A_SalesOrderItmSubsqntProcFlow_J` |
| `get_related_billing_documents` | `query_A_SalesOrderItmSubsqntProcFlow_M` |

搜尋輸入使用 `SoldToParty`、`SalesOrderDate.ge/le`、`OverallSDProcessStatus`；單筆及跨文件輸入使用 `SalesOrder`。狀態值使用 SAP `A/B/C`。不加入企業概念、文件關係、業務定義、情境提示或 policy 說明。

### B Typed Baseline：中度可讀

B 允許「操作、欄位、約束」可讀，但不提供能協助 Agent 進行企業流程推理的語意：

- 使用 canonical business tool／parameter 名稱。
- 提供一般功能句、required、型別、長度、日期格式與 enum。
- 可說明「使用銷售訂單識別碼取得交貨資料」這種最低限度的呼叫用途。
- 不得出現 `Sales Order generates Outbound Delivery`、跨文件關係解釋、PGI／會計過帳定義、狀態流程意義、建議呼叫順序、情境提示、唯讀 policy 或 fallback 說明。

B 的描述只能回答「如何正確呼叫」，不能回答「依企業流程如何選擇工具」。

### C Semantic Tools

C 使用 Phase 04 Semantic Compiler 產物，包含企業概念、文件關係、操作目的、參數業務意義、適用情境與唯讀政策。C catalog 必須與 Phase 04 catalog byte-for-byte 相同。

## 原型產物

以 strict model/evidence gate 執行：

```powershell
$env:UV_CACHE_DIR='D:\lab_project\3way_match\webmcp_semantic_erp_agent\.uv-cache'
uv run semantic-model compile-conditions `
  --model semantic_models\sap_sd\model.yaml `
  --evidence semantic_models\sap_sd\evidence\tenant-binding-evidence.json `
  --official-evidence semantic_models\sap_sd\evidence\official-s4hana-2023.json `
  --schema semantic_models\sap_sd\model.schema.json `
  --output-dir build\phase-05
```

輸出為 `a-technical-tools.json`、`b-typed-tools.json`、`c-semantic-tools.json` 與 `conditions-manifest.json`。生成檔位於 ignored `build/`，不提交版本庫。Manifest 固定記錄 model、compiler、artifact hash、canonical mapping 與共享 invariant。

## 註冊與 canonicalization

`registerConditionTools()` 對 A/B/C 使用同一註冊流程，只將 `name`、`description`、`inputSchema`、`annotations` 與 `execute` 投影給 WebMCP；`operationId`、mapping、manifest、outputSchema 與 evidence 不進入 Agent context。

A 的 `SalesOrder`、技術搜尋欄位與 SAP 狀態碼轉成 B/C 的 `sales_order_id`、`criteria.*` 與 business status；B/C 使用 identity mapping。未知條件、額外欄位、錯誤 hash 或非 allowlist operation 一律 fail closed，不 fallback 到 mock、OData V4 或其他來源。

三組 smoke：

```powershell
node scripts\smoke_webmcp_registration.mjs `
  build\phase-05\a-technical-tools.json `
  build\phase-05\b-typed-tools.json `
  build\phase-05\c-semantic-tools.json
```

## 通過條件

- 三組各註冊恰好四個工具，且等價輸入命中相同 action 與 canonical arguments。
- 三組 output schema、read-only annotation、輸入能力與 runtime target 完全一致。
- A 不暴露 business semantics；B 不暴露企業關係、情境提示、流程定義或 policy；C 由 validated model 產生完整語意。
- 相同模型重跑產生 byte-for-byte 相同 artifacts；strict gate 失敗時不產生新 suite。
- 既有 Phase 04 tests/smoke 與 Phase 05 新增 tests/smoke 全數通過。

## 論文素材

保留 A/B/C 工具契約比較表、B 的語意允許／禁止規則、shared-runtime invariant、canonicalization mapping、hash identity 與 leakage negative-test 結果，供 Phase 08 實驗與 Phase 09 論文整合使用。
