# Phase 2：SAP SD 語意模型設計

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

- SAP SD 最小語意模型草稿。
- 四個工具的輸入／輸出表。
- SAP 技術欄位與業務欄位的對照表。

## 通過條件

每一個模型欄位都能說明它支援哪一個工具、哪一類任務或哪一項評估指標。
