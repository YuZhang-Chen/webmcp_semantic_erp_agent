# Phase 06：WebMCP 直接串接 SAP OData V2

## 目標與範圍

本階段把 Phase 05 的 A/B/C 條件目錄接到瀏覽器端，完成一個以繁體中文呈現的 SAP SD 跨文件查詢工作台。頁面只保留本實驗需要的功能：銷售訂單查詢、訂單明細、外向交貨與請款文件流程，以及 WebMCP 註冊狀態。

本階段不實作寫入、不引入 OData V4、不加入 mock fallback，也不把自然語言聊天框放進網站；自然語言任務由 ChatGPT／Codex Agent 發出，網站提供結構化工作台與四個瀏覽器工具。

## 實作架構

```text
ChatGPT／Codex Agent
        │ WebMCP execute()
        ▼
frontend/src/App.tsx
        │ 共用 handler（UI 與 WebMCP 相同）
        ▼
frontend/src/runtime/odata.ts
        │ allowlist + GET-only + HTTPS + 分頁正規化
        ▼
Shared transport profile
        ├─ direct-browser：瀏覽器直接讀取 SAP OData V2
        └─ local-gateway：瀏覽器同源 GET → localhost Gateway → SAP OData V2
```

啟動器 `scripts/serve_phase06.py` 提供靜態前端、選定的 A/B/C catalog、runtime binding artifact 與 transport profile。`direct-browser` 延續瀏覽器直連；`local-gateway` 由同一個 localhost process 提供受限 `/api/odata/{service_id}/{entity_set}` relay。Gateway 僅負責 SAP TLS、certificate pin、Basic Auth 與 GET relay，不承擔業務 mapping，也不接受任意上游網址。

## 頁面與工具

| WebMCP tool | 頁面行為 | SAP 操作 |
| --- | --- | --- |
| `search_sales_orders` | 套用客戶、日期與狀態條件，更新結果表 | `GET` SalesOrderCollection |
| `get_sales_order` | 選取訂單並更新摘要與明細 | `GET` SalesOrderCollection(key) |
| `get_related_deliveries` | 顯示訂單的交貨節點 | `GET` OutboundDeliveryCollection |
| `get_related_billing_documents` | 顯示訂單的請款節點 | `GET` BillingDocumentCollection |

UI 操作與 WebMCP `execute()` 共用同一組 application handlers，因此 Agent 回傳的結構化結果與畫面狀態一致。畫面只顯示治理後的摘要、狀態、擷取時間與 provenance，不顯示原始 OData payload、完整 URL 或憑證。

## Runtime contract

語意模型 `semantic_models/sap_sd/model.yaml` 已升版至 `0.5.0`，並宣告三個 OData V2 runtime service selector：

- `SAP_ODATA_BASE_URL`
- `SAP_DELIVERY_ODATA_BASE_URL`
- `SAP_BILLING_ODATA_BASE_URL`

`src/semantic_model/runtime.py` 會從已通過 Phase 03 strict validation 的模型編譯出 `build/phase-06/runtime-bindings.json`。artifact 包含 model/version、操作輸入輸出 schema、private binding、GET-only policy 與 SHA-256；瀏覽器啟動時會驗證 artifact hash、model identity 與 service selector。

前端 runtime 規則如下：

1. 只接受 HTTPS service root，拒絕 query、fragment、userinfo 與非 allowlist service；Gateway profile 只把 service id 暴露給瀏覽器。
2. 僅送出 `GET`，固定 `credentials: omit`、`cache: no-store`，並限制 `$select`、`$filter`、`$top` 與 `__next` 分頁。Gateway 另以 CA trust 加 SHA-256 certificate pin 驗證 SAP peer。
3. SAP OData V2 回應只取 `d.results`；下一頁必須仍在相同 service root，最多正規化 50 筆。
4. 日期、狀態與文件關聯在 client 端轉成 canonical schema；錯誤只回傳可解釋的 sanitized code/message。
5. direct-browser profile 的任何 CORS、TLS、驗證或 OData schema 失敗都停止；local-gateway profile 只作為因目標瀏覽器憑證相容性限制而明確選擇的固定 transport，不作自動 fallback。

## 建置與啟動

在 `webmcp_semantic_erp_agent` 執行：

```powershell
$env:UV_CACHE_DIR='D:\lab_project\3way_match\.uv-cache-semantic'
uv run python -m semantic_model.cli validate --model semantic_models/sap_sd/model.yaml --evidence semantic_models/sap_sd/evidence/tenant-binding-evidence.json --official-evidence semantic_models/sap_sd/evidence/official-s4hana-2023.json --schema semantic_models/sap_sd/model.schema.json
uv run python -m semantic_model.cli compile-conditions --model semantic_models/sap_sd/model.yaml --evidence semantic_models/sap_sd/evidence/tenant-binding-evidence.json --official-evidence semantic_models/sap_sd/evidence/official-s4hana-2023.json --schema semantic_models/sap_sd/model.schema.json --output-dir build/phase-05
uv run python -m semantic_model.cli compile-runtime --model semantic_models/sap_sd/model.yaml --evidence semantic_models/sap_sd/evidence/tenant-binding-evidence.json --official-evidence semantic_models/sap_sd/evidence/official-s4hana-2023.json --schema semantic_models/sap_sd/model.schema.json --output build/phase-06/runtime-bindings.json

cd frontend
npm install --ignore-scripts
npm run build
cd ..

uv run python scripts/serve_phase06.py --condition A --transport local-gateway --port 5173
```

`--condition` 必須是 `A`、`B` 或 `C`；`--transport` 可選 `direct-browser` 或 `local-gateway`，A/B/C 評估時必須固定同一 profile。local-gateway 需要本機 `.env` 額外提供 `SAP_ODATA_CA_CERT` 與 `SAP_ODATA_CERT_SHA256`。預設綁定與 `.env` 只在本機使用，不能提交版本庫。若要測試另一條件，先停止目前啟動器，再重新指定 `--condition`。
啟動後請以 `http://localhost:5173` 開啟工作台；啟動器預設 host 為 `localhost`。

## 驗證與通過條件

自動化檢查：

```powershell
$env:UV_CACHE_DIR='D:\lab_project\3way_match\.uv-cache-semantic'
uv run python -m pytest -q
node scripts/smoke_webmcp_registration.mjs build/phase-05/a-technical-tools.json build/phase-05/b-typed-tools.json build/phase-05/c-semantic-tools.json
```

目前已驗證：Python 測試全數通過、前端 Vite production build 通過、Node WebMCP registration smoke 通過、啟動器可提供 `/runtime/config.json`、`/runtime/tool-catalog.json`、`/runtime/bindings.json` 且使用 `Cache-Control: no-store`。

人工 acceptance gate：在支援 WebMCP 的目標瀏覽器開啟頁面，確認能發現四個工具，依序執行搜尋、訂單明細、交貨與請款查詢；同時確認空結果、分頁、失敗與 provenance 均可解釋。此 gate 需要目標瀏覽器與可用的 SAP tenant，不能由離線 fixture 取代。

## 安全與資料治理

- 來源遵循 `webmcp.sap_sd.odata` 與 `webmcp.sap_sd.semantic_model` catalog；不借用其他 SAP adapter、analytics snapshot、fixture 或 mock。
- SAP 帳密只由本機 `.env` 提供；不寫入 artifact、tool catalog、前端 bundle、文件或 git。
- 不記錄 tenant endpoint、raw `$metadata`、raw rows、完整錯誤 payload 或業務憑證。
- 若 runtime config、model hash、binding hash 或 service selector 不一致，啟動或執行立即失敗。

## 後續工作

完成目標瀏覽器的四工具 live acceptance 後，再把 sanitized 結果與 request trace 補入研究紀錄；任何 binding 或 OData schema 變更都必須重新跑 Phase 03 strict gate、Phase 05 條件編譯與 Phase 06 runtime artifact 驗證。
