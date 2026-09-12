# Phase 1：Browser–SAP 連線閘門與 Semantic Analytics 設計參考

## 階段狀態

- 狀態：完成
- 完成日期：2026-09-13
- 設計產出：[Semantic Analytics 設計參考摘要](../semantic-analytics-reference.md)

## 前置技術閘門

在投入 Semantic Model 與 WebMCP 工具實作前，先使用目標瀏覽器及實際 SAP 教學環境依序驗證：

1. 成功讀取 OData `$metadata`。
2. 成功執行一筆 EntitySet GET。
3. 成功執行一筆帶 `$filter` 的 GET。
4. 記錄 HTTP 狀態、CORS preflight、TLS／Windows 信任憑證行為、驗證結果與實際 OData 版本。

帳號密碼僅由本機 `.env` 提供，SAP 受信任憑證存放於 Windows 憑證存放區。本驗證只適用於隔離的教學原型，不將帳密或憑證內容寫入程式碼、文件、log 或版本庫。

若任一測試因 CORS、TLS、驗證或 OData 服務設定失敗，立即停止本階段並請研究者共同處理；不得自行加入 proxy、destination、mock、替代端點或協定 fallback。四項驗證通過後，才進行以下 Semantic Analytics 參考分析。

### 閘門驗證結果

研究者在目標瀏覽器確認目前狀態與探針的完整 PASS 畫面一致：

| 驗證項目 | 結果 | 安全紀錄 |
| --- | --- | --- |
| `$metadata` | PASS；HTTP 200；OData 2.0 | 22 個 EntitySets；選定 `A_SalesOrder`；不記錄 endpoint 或 raw metadata |
| EntitySet GET | PASS；HTTP 200 | V2 `d.results`；取得 1 row；business key 已遮蔽 |
| `$filter` GET | PASS；HTTP 200 | 以取得的 `SalesOrder` 執行等值 filter；取得 1 row；值已遮蔽 |
| CORS／TLS／Auth | PASS | Cross-origin Authorization、preflight、目前瀏覽器 HTTPS session 與驗證均成功 |

測試由 `scripts/browser_sap_probe.py` 提供本機頁面；SAP GET 由瀏覽器直接執行，不經 proxy，probe server 不接收 SAP response rows。畫面只顯示狀態、結構摘要及截短 hash。

## 目的

從既有 `semantic_analytics/` 實作理解語意建模方式，僅作為設計參考，不將其列為本研究比較對象，也不整合成第二套架構。

## 本階段工作

1. 觀察 entity、relationship、operation 與 business description 的角色。
2. 觀察模型版本、驗證與治理資訊如何被保存。
3. 區分企業語意、操作語意、系統綁定與治理控制。
4. 只萃取本研究四個工具所需的最小欄位。

## 最小欄位候選

```text
entities
relationships
operations
parameters
business_descriptions
odata_bindings
read_only_policy
output_schema
model_version
```

## 明確不做

- 不比較 Semantic Analytics 與本研究的架構效能。
- 不把既有分析資料庫當成 SAP ERP runtime source。
- 不建立通用企業 ontology framework。
- 不因參考專案已有功能而擴大本研究工具範圍。

## 階段產出

- [x] 「沿用、調整、不採用」對照表。
- [x] 最小治理欄位定義。
- [x] 一個 SAP SD 語意模型範例草稿。

三項產出均位於 [Semantic Analytics 設計參考摘要](../semantic-analytics-reference.md)。

## 論文素材

相關技術與研究方法中的設計依據，並明確說明 `semantic_analytics` 是參考來源而非實驗 baseline。

## 實作紀錄

- 確認 `semantic_analytics/` 的 `sales.semantic.model` 是受治理 metadata；沒有把 analytics SQLite、snapshot 或 fixture 當成 live SAP runtime source。
- 參考 public catalog、business definitions、physical model、versioned rules、model loader、metadata graph builder 與 strict tool registry。
- 將可借鑑內容收斂為 public／private 分層、版本與 hash、交叉引用驗證、封閉操作集合、strict input 與安全 output。
- 不採用 analytics metric engine、SQL planner、runtime semantic service、Facade 或任意 graph traversal。
- 固定 Agent → WebMCP tool → browser OData GET → SAP → structured result；Agent 不接觸 OData 細節或 credentials。
- Phase 02 只可把已驗證的 `A_SalesOrder`／`SalesOrder` 當作 binding evidence；其餘技術映射仍須由 tenant `$metadata` 核對。
