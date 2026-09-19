# 研究範圍與已完成設計

本文件記錄 WebMCP ERP Agent 研究的固定範圍與實際完成的兩項研究。SAP SD 語意模型的現行契約見 [`semantic_models/sap_sd/model.yaml`](../semantic_models/sap_sd/model.yaml)，逐次分數、排程、事件投影與統計結果見 [`research_artifacts/`](../research_artifacts/README.md)。

## 研究目的

本研究探討工具介面的語意增強程度，是否影響 LLM Agent 執行 SAP SD 銷售訂單、外向交貨及請款文件唯讀查詢時的工具選擇、參數生成與任務完成表現。

主要指標為 Tool Selection Accuracy、Parameter Accuracy 與 Task Success Rate。工具呼叫步數、執行時間、多餘呼叫與錯誤類型作為輔助描述，不取代主要指標。

## 系統與任務範圍

研究情境固定為下列 SAP SD 文件關係：

```text
Customer
   └─ places → Sales Order
                    ├─ generates → Outbound Delivery
                    └─ generates → Billing Document
```

Agent 可使用的操作是封閉集合：

| Canonical operation | 業務目的 |
| --- | --- |
| `search_sales_orders` | 依允許條件搜尋銷售訂單 |
| `get_sales_order` | 取得單筆銷售訂單 |
| `get_related_deliveries` | 由銷售訂單追蹤相關外向交貨 |
| `get_related_billing_documents` | 由銷售訂單追蹤相關請款文件 |

任務分成 D1 單一文件查詢、D2 已知訂單跨文件查詢、D3 條件搜尋後跨文件查詢。D1–D3 是分析用任務類別，不代表固定工具呼叫順序。

## 工具介面條件

| 條件 | Agent 可見資訊 |
| --- | --- |
| A Technical | OData／SAP 技術名稱與呼叫所需 schema |
| B Typed | 一般功能描述、業務化參數名稱、型別與格式限制 |
| C Semantic | 經驗證模型產生的企業概念、文件關係、操作目的、適用情境與唯讀政策 |

三組共用同一組 canonical operations、SAP binding、執行器、輸出 schema、頁面狀態及評分規則。Study 1 的主要自變因為 Agent 可見工具介面的語意程度；Study 2 另以任務難度設定工具呼叫額度。

## 已完成研究

| 研究 | 設計 | 有效評分 |
| --- | --- | ---: |
| Study 1：主要整合驗證 | 20 題 × 3 條件 × 每條件 3 次重複 | 180 |
| Study 2：受限額度補充研究 | 12 題 × 3 條件 × 每條件 2 次重複 | 72 |

Study 1 共保存 182 次執行嘗試，其中一個 slot 經歷兩次無效嘗試，最終由 replacement 完成；無效嘗試不列入 180 筆有效評分。Study 2 為 72 筆有效評分，沒有缺失或替代 run。

Study 2 依任務難度設定 D1=1、D2=2、D3=3 次工具呼叫額度。超額呼叫是有效的研究失敗結果，基礎設施或 SAP 服務失敗才依 protocol 判定無效並處理 replacement。兩項研究各自計算分母與統計，不合併分析。

Phase 07 pilot 及其方法開發紀錄不屬於這兩項研究的分析樣本。研究結果和可公開的去識別資料以 `research_artifacts/` 固定版本為準；原始 Ground Truth、完整提示、Agent 原始答案及完整執行 log 留在研究者私有儲存。

## 固定系統邊界與限制

- SAP runtime 使用已驗證的 OData V2；所有操作僅允許 HTTP GET，不允許寫入或 silent fallback。
- 網站提供共用工作台與 WebMCP tools，不內嵌 LLM 或 Agent Controller；Agent 自行選擇工具與順序。
- `semantic_analytics/` 是設計參考，不是 runtime dependency、資料來源或研究 baseline。
- 研究範圍不包括通用 SAP SD ontology、交易寫入、OData V4 正式比較或不同組別的 UI／執行層差異。
- Study 1 的受控 120 秒逾時中斷證據已豁免；因此不主張已驗證執行期逾時控制。八次工具呼叫上限由離線 scorer 判定。

各階段的實作決策與驗證方式保存在 [`docs/phases/`](phases/README.md)；它們是方法紀錄，不取代現行模型契約或正式研究結果。
