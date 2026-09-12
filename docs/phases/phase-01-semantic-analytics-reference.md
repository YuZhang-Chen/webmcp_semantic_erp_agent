# Phase 1：Browser–SAP 連線閘門與 Semantic Analytics 設計參考

## 前置技術閘門

在投入 Semantic Model 與 WebMCP 工具實作前，先使用目標瀏覽器及實際 SAP 教學環境依序驗證：

1. 成功讀取 OData `$metadata`。
2. 成功執行一筆 EntitySet GET。
3. 成功執行一筆帶 `$filter` 的 GET。
4. 記錄 HTTP 狀態、CORS preflight、TLS／Windows 信任憑證行為、驗證結果與實際 OData 版本。

帳號密碼僅由本機 `.env` 提供，SAP 受信任憑證存放於 Windows 憑證存放區。本驗證只適用於隔離的教學原型，不將帳密或憑證內容寫入程式碼、文件、log 或版本庫。

若任一測試因 CORS、TLS、驗證或 OData 服務設定失敗，立即停止本階段並請研究者共同處理；不得自行加入 proxy、destination、mock、替代端點或協定 fallback。四項驗證通過後，才進行以下 Semantic Analytics 參考分析。

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

- 「沿用、調整、不採用」對照表。
- 最小治理欄位定義。
- 一個 SAP SD 語意模型範例草稿。

## 論文素材

相關技術與研究方法中的設計依據，並明確說明 `semantic_analytics` 是參考來源而非實驗 baseline。
