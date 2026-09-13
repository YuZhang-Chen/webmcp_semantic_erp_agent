# Phase 2：SAP SD 語意模型設計

## 階段狀態

- 狀態：完成
- 完成日期：2026-09-13
- Canonical 產出：[SAP SD 最小語意模型設計](../sap-sd-semantic-model-design.md)
- 模型狀態：`draft`；必須通過 Phase 03 validation 才能成為 `validated`

## 目的

在不寫執行程式的前提下，先完成 SAP SD 跨文件查詢的企業語意定義。

## 固定企業概念

```text
Customer
   ↑ belongs to
Sales Order
   ├─ generates → Outbound Delivery
   └─ generates → Billing Document
```

## 固定操作

| 操作 | 業務目的 |
| --- | --- |
| `search_sales_orders` | 依條件搜尋銷售訂單 |
| `get_sales_order` | 取得單筆訂單 |
| `get_related_deliveries` | 依訂單追蹤外向交貨 |
| `get_related_billing_documents` | 依訂單追蹤請款文件 |

## 本階段工作

1. 為四個 entity 定義業務描述。
2. 定義訂單、交貨與請款的關係。
3. 定義每個操作的用途與適用情境。
4. 定義參數的業務名稱、型別、格式與必填規則。
5. 定義輸出欄位與 OData binding 的候選映射。
6. 將 tenant `$metadata` 核對列為後續執行前檢查，不以猜測取代證據。

## 階段產出

- [x] SAP SD 最小語意模型草稿。
- [x] 四個工具的輸入／輸出表。
- [x] SAP 技術欄位與業務欄位的對照表。

三項產出均位於 [SAP SD 最小語意模型設計](../sap-sd-semantic-model-design.md)。目前只有 Phase 01 已證實的 `A_SalesOrder`／`SalesOrder` 可標示為 tenant-verified name；其餘 private binding 均明示為 `unverified`，不得以命名慣例補值。

## 通過條件

每一個模型欄位都能說明它支援哪一個工具、哪一類任務或哪一項評估指標。

## 實作紀錄

- 固定四個 entity、三條文件關係與四個 canonical operations，沒有擴大研究工具集合。
- 定義搜尋條件、單筆與跨文件查詢參數的業務名稱、型別、格式、必填及 cross-field 規則。
- 定義三組共用的 tenant-neutral output schemas 與 trace fields，禁止洩漏 endpoint、credential、private binding 或 raw SAP row。
- 以 operation binding 與 output field mapping 表區分 `tenant_verified_name`、`partially_verified` 與 `unverified`。
- 建立欄位對工具、D1／D2／D3 任務及主要評估指標的 coverage evidence。
- 明定 Phase 03 fail-closed 交接：缺少 tenant metadata evidence、非 GET、未知欄位或未列入 operation 時不得產生 active tool。
