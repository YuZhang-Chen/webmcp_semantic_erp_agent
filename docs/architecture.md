# 系統架構與研究邊界

```text
建置期
Governed Semantic Model
  ├─ entities / relationships / business descriptions
  ├─ operations / parameters / output schemas
  ├─ OData bindings
  └─ read-only policy / model version
             │ validate + deterministic compile
             ▼
      A / B / C Tool Catalogs ─────────────┐
                                           │ import / register
執行期                                     ▼
User → LLM Agent → Browser-native WebMCP tool
                                           │ execute(args)
                                           ▼
                          Shared Application Actions / OData Client
                                           │ HTTPS GET only
                                           ▼
                                  SAP OData V2 → SAP ERP
```

語意層不是 Agent 執行期查詢的服務。生成檔帶有 model hash、model version、compiler version 與 artifact hash，使每次實驗可追溯到同一模型。本階段協定固定為 SAP OData V2；不自動 fallback 到 V4。

SAP binding 採 multi-source evidence precedence：固定版本的 SAP S/4HANA 2023 / S4CORE 108
官方 API 定義先界定 service、property 與完整 code domain；tenant `$metadata` 再證明實際
可用性、EDM type 與長度；known-case runtime evidence 只證明 representative semantic values；
最後才由 Semantic Binding Validation 決定是否可交給 compiler。

本研究原型不設置自建應用後端；SAP ERP 及其 OData 服務是系統後端。Web UI 與 WebMCP tool 共用瀏覽器端的 Application Actions，直接向 SAP OData V2 發出唯讀請求。V2 browser gate 由目前 probe 驗證；V4 不作 fallback。

## 資料流

1. Agent 根據工具 schema 選擇操作並產生參數。
2. 瀏覽器生成程式把各組公開參數映射回 canonical business arguments。
3. 共用 Application Actions 在瀏覽器端驗證 allowlist、格式、長度與必填欄位。
4. OData client 由模型 binding 生成 `$filter`、`$select`、`$top`，直接向 SAP 發出 HTTPS GET。
5. OData V2 client 將 `d.results` 正規化，並回傳 protocol、model version、擷取時間與 request id。

## 原型部署與安全邊界

- SAP 帳號密碼由本機 `.env` 提供，只限隔離的教學原型，不得提交版本庫或宣稱為正式部署的祕密管理方式。
- SAP 受信任憑證安裝於 Windows 憑證存放區，不打包進網站或 WebMCP tool definitions。
- 第一個技術閘門必須在目標瀏覽器中驗證 CORS、TLS、驗證流程與 OData 回應；未通過即停止，由研究者共同處理，不自行加入 proxy、destination 或其他替代路徑。
- 所有 SAP 操作只允許 HTTP GET；不自動 fallback 到 mock、舊端點或其他協定。

## 實驗控制

A、B、C 使用同一執行器、同一 OData binding 與同一輸出，只改變暴露給 Agent 的工具名稱、描述與參數語意。建議主要實驗為 20 tasks × 3 variants × 3 repetitions；另以 5 個 live SAP 案例報告系統可行性。Ground truth 必須由另一個評分程序載入，不能進入 Agent context。
