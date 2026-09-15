# Phase 00 研究範圍基線

本文件是 Phase 00 的固定研究基線。後續設計若改變研究工具、A／B／C 條件、主要指標、系統邊界或排除事項，必須先說明其對研究效度的影響，再更新本文件。

## 研究目的與研究問題

本研究探討：當 LLM Agent 執行 SAP SD 銷售訂單、外向交貨與請款文件的跨文件查詢任務時，工具介面的語意增強程度是否會影響 Agent 的工具選擇、參數生成與任務完成表現。研究原型僅改變 Agent 可見的工具介面，讓 A Technical、B Typed、C Semantic 三個條件共用相同的資料、執行邏輯、網站畫面與評分方法，以隔離「工具語意增強程度」這個自變因。

主要研究問題為：

> 在其他執行條件固定時，A Technical、B Typed、C Semantic 三種工具介面是否造成 Tool Selection Accuracy、Parameter Accuracy 與 Task Success Rate 的差異？

虛無假設為三組在三項主要指標上沒有差異；對立假設為至少一組存在差異。`C > B > A` 僅作為方向性預期，不作為 Phase 00 的通過條件。

## 固定查詢情境

研究情境固定為 SAP SD 的唯讀文件查詢：

```text
Customer
   └─ places → Sales Order
                    ├─ generates → Outbound Delivery
                    └─ generates → Billing Document
```

研究任務只允許以下三類：

| 難度 | 任務類型 | 最小行為 |
| --- | --- | --- |
| D1 | 單一文件查詢 | 搜尋訂單或讀取已知訂單 |
| D2 | 已知訂單跨文件查詢 | 由已知訂單查交貨、請款，或兩者皆查 |
| D3 | 條件搜尋後跨文件查詢 | 先依條件找出訂單，再查交貨、請款，或兩者皆查 |

D1、D2、D3 是任務分類，不是 Agent 的固定流程。正式執行時不得硬編碼工具順序。

## 變因定義

| 類型 | 變因 | 固定定義或操作化方式 |
| --- | --- | --- |
| 自變因 | 工具介面的語意增強程度 | 三個水準：A Technical、B Typed、C Semantic |
| 依變因 | Tool Selection Accuracy | 正確工具決策數 ÷ 可評分工具決策數；Ground Truth 定義可接受工具，無效或多餘呼叫列為錯誤決策 |
| 依變因 | Parameter Accuracy | 正確 canonical 參數值數 ÷ 可評分參數值數；缺漏、錯誤型別、格式或值均列為錯誤 |
| 依變因 | Task Success Rate | 完成 Ground Truth 要求的 run 數 ÷ 全部有效 run 數；逐一 run 以成功／失敗計分 |
| 控制變因 | Canonical operations | 三組皆只有固定四工具，不增減操作 |
| 控制變因 | 執行與資料綁定 | 相同 Shared Application Actions、SAP OData binding、查詢限制與正規化輸出；A/B/C 固定使用同一 transport profile |
| 控制變因 | 網站與頁面狀態 | 相同畫面、搜尋條件、已選訂單、結果呈現與狀態轉換規則 |
| 控制變因 | 任務與提示 | 相同 task、system prompt、使用者措辭、上下文及可用工具數 |
| 控制變因 | Agent 條件 | 相同模型、模型版本、推理設定、temperature、工具呼叫上限與逾時設定 |
| 控制變因 | SAP 條件 | 相同 tenant、OData 版本、權限、案例集與資料時間基線；每次 run 記錄可追溯識別資訊 |
| 控制變因 | 評分與紀錄 | 相同 Ground Truth、canonicalization、錯誤分類、logger 與 scorer；Ground Truth 不進入 Agent context |
| 控制變因 | 執行順序 | Pilot 前決定平衡或隨機化策略，避免組別順序與暫時性系統狀態混淆 |

三項主要指標固定後不得以 execution time、呼叫步數或人工主觀評分取代。執行時間、多餘呼叫與錯誤類型只能作為輔助指標。

## A／B／C 條件

三組公開契約可使用不同名稱與描述，但進入執行層前都必須正規化成相同的 canonical operation 與 canonical business arguments。

| 條件 | Agent 可見資訊 | 不得出現的資訊 |
| --- | --- | --- |
| A Technical | OData／SAP 技術導向名稱、技術欄位名稱，以及呼叫成立所需的最低限度 schema | 文件關係、操作目的、參數業務意義、情境提示 |
| B Typed | 一般功能描述、業務化參數名稱、型別、必填與格式限制 | 完整企業概念、Sales Order 到 Delivery／Billing 的關係說明、情境化使用時機 |
| C Semantic | 經驗證模型產生的企業概念、文件關係、操作目的、參數業務意義、適用情境與唯讀政策 | 未經 Semantic Model 驗證或由實作者臨時補寫的提示 |

公平比較的硬性限制：

- 三組共用完全相同的四個 canonical operations。
- 三組共用完全相同的 SAP binding、HTTP GET 執行器與輸出 schema。
- 三組共用完全相同的網站 UI 與頁面狀態；不能用 UI 差異提示某一組。
- 條件差異只存在於 Agent 可見的工具名稱、描述與參數語意。
- A 與 B 不得由 C 的完整描述刪字產生後仍殘留文件關係或業務提示。
- C 必須由受治理且通過驗證的 Semantic Model 編譯產生，不得手工維護成另一份真相。

## 固定四工具與任務難度

| Canonical operation | 固定業務目的 | 最小輸入概念 | 支援難度 |
| --- | --- | --- | --- |
| `search_sales_orders` | 依允許條件搜尋銷售訂單 | 一組經 allowlist 的搜尋條件 | D1、D3 |
| `get_sales_order` | 取得單筆銷售訂單 | 銷售訂單識別碼 | D1；必要時支援 D2、D3 的確認步驟 |
| `get_related_deliveries` | 由銷售訂單追蹤相關外向交貨 | 銷售訂單識別碼 | D2、D3 |
| `get_related_billing_documents` | 由銷售訂單追蹤相關請款文件 | 銷售訂單識別碼 | D2、D3 |

工具清單是封閉集合。分頁、驗證、結果正規化與 OData 查詢組裝是四工具內部執行責任，不得為了實作方便新增為 Agent 可見工具。

## 最小系統邊界

下列文字圖是納入版控的正式邊界圖；本機另保留可編輯 draw.io 與 PNG 預覽，但 `docs/diagrams/` 依版控政策不發布。

```text
建置期：Semantic Model → Validation／Compiler → A／B／C Tool Catalogs
                                                    │
執行期：使用者 → ChatGPT／Codex Agent → WebMCP Tools（只載入一組條件）
                                      → Shared Application Actions
                                      → Browser OData V2 Client
                                      → direct-browser 或 localhost Gateway
                                      → SAP OData V2 → SAP ERP

網站工作台 ──共用搜尋條件、已選訂單與文件結果── WebMCP Tools

實驗外部：Ground Truth／Scorer ← Agent trace、canonical calls、結果摘要
```

邊界判定：

- `webmcp_semantic_erp_agent/` 是獨立原型；`semantic_analytics/` 僅是設計參考，不是 runtime dependency、資料來源或實驗 baseline。
- 系統保留 direct-browser 對照；因目標瀏覽器憑證相容性限制，正式原型可使用明確選擇的 localhost Gateway。瀏覽器端 Application Actions、OData binding 與正規化輸出維持不變。
- Semantic Model 只在建置期驗證並編譯工具，不是執行期查詢服務。
- 網站只註冊工具、提供共用頁面狀態並顯示結果，不內嵌 LLM 或 Agent Controller。
- Agent 自行選擇工具及順序；系統不硬編碼訂單到交貨再到請款的流程。
- Ground Truth 與 scorer 位於 Agent context 外，只消費紀錄，不參與工具選擇。

## ChatGPT／Codex 與網站並排 wireframe

```text
┌──────────────────────────────────────┬──────────────────────────────────────┐
│ ChatGPT／Codex 對話區                │ SAP SD 網站工作台                    │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ 使用者任務                           │ [連線狀態] [唯讀] [OData V2]         │
│ 「找出符合條件的訂單，並確認…」      │                                      │
│                                      │ 搜尋條件                             │
│ Agent 推理與工具呼叫                 │ [Customer] [Date] [Status] [Search]  │
│ 1. 選擇目前條件的 WebMCP tool        │                                      │
│ 2. 產生公開參數                      │ 銷售訂單清單                         │
│ 3. 網站端正規化為 canonical args     │ ○ Order 1   ● Order 2   ○ Order 3    │
│                                      │                                      │
│ 最終答案                             │ 已選訂單與文件流程                   │
│ - 訂單摘要                           │ Sales Order                          │
│ - 相關交貨                           │   ├─ Outbound Delivery results       │
│ - 相關請款                           │   └─ Billing Document results        │
│                                      │                                      │
│ [Agent 看不到 Ground Truth／分數]     │ [結果摘要] [錯誤／空結果狀態]         │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

網站 wireframe 在 A、B、C 三組完全相同。實驗條件只改變 Agent 收到的 WebMCP tool contract，不改變網站的文字、元件、預設值或頁面狀態。

## 納入與排除規則

新增功能至少必須直接支援下列一項，否則不納入研究原型：

1. Semantic Model 的驗證或可追溯編譯。
2. A／B／C 條件隔離與公平控制。
3. Tool Selection Accuracy、Parameter Accuracy 或 Task Success Rate 的可靠計算。

即使符合其中一項，也不得破壞四工具封閉集合、唯讀政策或共同執行層。

Phase 00 明確排除：

- SAP 寫入交易及任何非 HTTP GET 操作。
- 通用企業 ontology 或可任意擴充的 ontology framework。
- 網站內嵌 Agent Controller、LLM orchestration 或隱藏式固定流程。
- 為不同實驗組別建立不同 UI、執行邏輯、輸出或資料來源。
- 將 `semantic_analytics/` 整合成 runtime service 或列為比較 baseline。
- 未經 tenant `$metadata` 驗證便固定 EntitySet、property、association 或 OData binding。
- OData V4 正式比較；V4 只能是後續、明確驗證後的延伸結果。
- 寫入 credential、tenant endpoint、原始 SAP rows 或完整 Ground Truth 至工具描述、文件或 Agent context。

## 後續階段交接條件

Phase 1 開始前，本文件以下內容視為凍結：

- 研究問題與三項主要指標。
- A Technical、B Typed、C Semantic 的差異邊界。
- 四個 canonical operations。
- D1、D2、D3 任務難度分類。
- 對話區與網站並排、網站不內嵌 Agent Controller 的操作模式。
- SAP 唯讀、OData V2 為主要協定、無自建應用後端的系統邊界。

Phase 1 必須先在目標瀏覽器與實際教學 SAP 環境驗證 `$metadata`、單筆 GET、帶 `$filter` GET、CORS、TLS 與驗證流程。驗證前，本文件不指定 SAP SD EntitySet 或技術欄位名稱。

## Phase 00 產出核對

| 要求 | 產出位置 | 狀態 |
| --- | --- | --- |
| 研究目的段落 | 研究目的與研究問題 | 完成 |
| 自變因、依變因與控制變因表 | 變因定義 | 完成 |
| 最小系統邊界圖 | 最小系統邊界的文字圖；本機另有 `diagrams/phase-00-system-boundary.drawio` | 完成 |
| 網站與 Agent 並排文字 wireframe | ChatGPT／Codex 與網站並排 wireframe | 完成 |
| 四工具清單與任務難度分類 | 固定四工具與任務難度 | 完成 |
| 排除事項與功能納入 gate | 納入與排除規則 | 完成 |
