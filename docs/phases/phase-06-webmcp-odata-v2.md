# Phase 6：WebMCP 直接串接 SAP OData V2

## 目的

將三組工具接到相同的瀏覽器與 SAP 執行邊界，完成已確認可用的 OData V2 實作。

## 執行資料流

```text
使用者在 ChatGPT／Codex 輸入自然語言任務
   ↓
ChatGPT／Codex Agent
   ↓ 發現目前開啟網站註冊的工具
Browser-native WebMCP（top-level page）
   ↓ tool execute() 讀取／更新目前頁面狀態
Shared Application Actions / OData Client
   ↓ validated HTTPS GET
SAP OData V2 → SAP ERP
```

## 網站互動設計

網站採用「Agent 對話區 + SAP SD 工作台」的並排使用方式。自然語言任務輸入位於 ChatGPT／Codex，而非網站內嵌的聊天框；右側網站是使用者與 Agent 共看的工作台。

```text
ChatGPT／Codex Agent                  SAP SD 跨文件查詢工作台
─────────────────────                ─────────────────────────
使用者：查詢訂單 100001 的            目前選取訂單：100001
出貨與請款狀態                        搜尋結果／訂單明細

Agent：呼叫網站工具                   訂單 → 外向交貨 → 請款文件
• get_sales_order                     文件狀態與擷取時間
• get_related_deliveries
• get_related_billing_documents
```

工作台至少維護三類前端狀態：搜尋條件與結果清單、目前選取的銷售訂單、訂單至交貨與請款的文件流程。四個 WebMCP tools 必須以網站既有邏輯處理這些狀態：查詢後更新結果，並將同一份結果回傳 Agent；Agent 不需要透過視覺辨識或脆弱的 DOM selector 推測資料。

### 四個工具與頁面狀態

| 工具 | 讀取或更新的頁面狀態 |
| --- | --- |
| `search_sales_orders` | 套用查詢條件並更新訂單結果清單。 |
| `get_sales_order` | 讀取或設定目前選取訂單，並更新訂單明細。 |
| `get_related_deliveries` | 依目前或指定訂單更新交貨節點與狀態。 |
| `get_related_billing_documents` | 依目前或指定訂單更新請款節點與狀態。 |

網頁可保留一般使用者可操作的結構化搜尋表單，作為非 WebMCP 瀏覽器的正常介面；但它不是 Agent 的自然語言入口，也不屬於 WebMCP tool invocation。

## 本階段工作

1. 在頂層頁面以 JavaScript 註冊 WebMCP tools。
2. 實作搜尋、選取訂單與文件流程三類頁面狀態。
3. 讓每個 tool execute() 同時更新網站工作台並回傳結構化結果。
4. 共用 Application Actions 在瀏覽器端再次驗證參數與唯讀政策。
5. 以本機環境變數提供原型所需的 SAP URL 與驗證設定；不得將值提交版本庫。
6. 實作 OData V2 `$filter`、`$select`、`$top` 與分頁正規化。
7. 以 `$metadata` 核對 entity set、欄位與文件關聯。
8. 保留 protocol、model version、retrieved time 與 request id 等 provenance。

## 安全限制

- 僅允許 HTTP GET。
- 本研究為隔離教學環境中的原型；SAP 帳號密碼由本機 `.env` 提供，不宣稱此方式適用於正式部署。
- SAP 受信任憑證由 Windows 憑證存放區管理，不放入 `.env`、前端原始碼或 WebMCP tool definitions。
- 網站不保存 OpenAI API key，也不透過網站內嵌的 LLM API 選擇工具。
- 不將實際端點、憑證或原始交易列提交至版本庫。
- 不自動 fallback 到 mock 或其他協定。
- 若直接連線因 CORS、TLS、驗證或 OData 設定失敗，停止並請研究者處理，不自行加入 proxy 或 destination。

## 明確排除

OData V4 不列入本階段正式實驗；若後續驗證成功，只作為 optional extension 或研究限制後的未來工作。

## 通過條件

Phase 1 的直接連線閘門已通過；四個工具能以人工測試直接查詢 SAP V2。在 ChatGPT／Codex 內建瀏覽器中，Agent 能發現目前頁面註冊的工具，工具呼叫後可同步更新網站工作台。空結果、錯誤、分頁與來源資訊均可解釋。
