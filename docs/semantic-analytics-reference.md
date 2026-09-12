# Phase 01：Semantic Analytics 設計參考摘要

## 結論

`semantic_analytics/` 適合借鑑的是「公開語意、私有綁定、治理資訊分層」以及「先驗證模型，再產生受限工具契約」的方法；它不是本原型的 runtime dependency、資料來源或實驗 baseline。

本原型的執行邊界固定如下：

```text
LLM Agent
  → Agent 可見的 WebMCP tool contract
  → 頁面內部 canonical operation
  → 頁面內部 OData V2 binding／HTTPS GET
  → SAP ERP
  → 正規化 structured result
  → LLM Agent
```

Agent 不需要知道 endpoint、EntitySet、OData query 組裝、帳密或原始 SAP row。這些都屬於頁面內部執行責任。

## 參考證據與來源邊界

本次只讀檢查下列 `semantic_analytics/` 設計證據：

- `semantic_models/sales/public_catalog.yaml`：公開 entity、metric、dimension、alias 與 business description。
- `semantic_models/sales/business_definitions.yaml`：aggregation、required filter、time semantic 與 allowed dimension。
- `semantic_models/sales/physical_model.yaml`：private table／column mapping、fact grain 與 relationship。
- `semantic_models/sales/rules/metrics.yaml`：具 version、effective date、status 的規則。
- `src/semantic_analytics/semantic/model_loader.py`：模型載入、交叉引用驗證、生命週期與 canonical SHA-256。
- `src/semantic_analytics/semantic/graph/builder.py`：只從已驗證模型建立 deterministic graph snapshot 與 graph hash。
- `src/semantic_analytics/application/semantic_tools.py`：封閉 tool registry、`extra=forbid` typed input、固定 envelope 與模型追溯資訊。

依 workspace 資料目錄，參考來源是 `sales.semantic.model`，分類為 `governed metadata`。本研究的 live SAP 仍是獨立外部來源；不得改讀 `sales.analytics.sqlite`、matching snapshot 或 synthetic fixture。

## 沿用、調整、不採用

| 判定 | 參考設計 | 本原型的決定 | 理由 |
| --- | --- | --- | --- |
| 沿用 | Public／business／physical metadata 分層 | Agent-visible semantic contract 與 private OData binding 分離 | 防止 endpoint、技術欄位與 credentials 進入 Agent context |
| 沿用 | Model ID、version、status、hash | 每次編譯產物保存 model／compiler／artifact identity | 支援 A／B／C 實驗可重現性 |
| 沿用 | Relationship 具方向與明確端點 | 固定 Customer、Sales Order、Delivery、Billing 關係 | 支援 C Semantic 的文件流程描述 |
| 沿用 | 封閉 registry 與 strict typed input | 只允許四個 canonical operations，拒絕額外參數 | 保持 Tool Selection 與 Parameter Accuracy 可評分 |
| 沿用 | Public response 不洩漏 physical mapping | structured result 只回傳研究所需欄位與追溯摘要 | Agent 不需要理解 OData 細節 |
| 調整 | Analytics 的 fact／metric／dimension 模型 | 改成 SAP SD 文件 entity／relationship／operation | 本研究是文件查詢，不是聚合分析 |
| 調整 | SQL table／column physical model | 改成 browser-side OData V2 EntitySet／property／query binding | 無 SQLite 與自建應用後端 |
| 調整 | Backend ToolRegistry／Pydantic envelope | 改成 WebMCP tool schema、頁面 action 與 browser normalization | 執行位置在目標頁面 |
| 調整 | Dataset snapshot identity | 改記 tenant-neutral case baseline、metadata hash 與擷取時間 | 不保存 raw SAP rows 或 tenant endpoint |
| 不採用 | Semantic knowledge service／graph query API | 不在 runtime 啟動第二套語意服務 | 語意模型只在建置期驗證與編譯 |
| 不採用 | Metric rules、derived expression、aggregation engine | Phase 01 不納入 | 四工具不計算分析 metric |
| 不採用 | 任意 graph traversal 或 ontology framework | 只保存三條固定文件關係 | 避免擴大研究變因與工具範圍 |
| 不採用 | SQL planner、database provider、Facade | 不整合 | WebMCP 頁面直接對 SAP 執行 HTTPS GET |

## 最小治理欄位

| 欄位 | 可見性 | 必要約束 | 支援目的 |
| --- | --- | --- | --- |
| `model_id` | 編譯與紀錄 | 穩定、非空 | 辨識模型 |
| `model_version` | Agent contract metadata／紀錄 | 每次語意變更遞增 | 實驗重現 |
| `status` | 建置期 | `draft`、`validated`、`active`、`retired` | 阻止未驗證模型發布 |
| `entities` | C Semantic | 穩定 ID 與 business description | 企業概念 |
| `relationships` | C Semantic | source、target、predicate、direction | 跨文件工具選擇 |
| `operations` | 各組編譯來源 | 只允許固定四項 | Tool Selection Accuracy |
| `parameters` | 依 A／B／C 編譯 | type、required、format、allowlist | Parameter Accuracy |
| `output_schema` | 三組共用 | strict、tenant-neutral、不得含 raw row | Task Success 與公平控制 |
| `odata_bindings` | 頁面內部 | 必須由 tenant `$metadata` 核對 | 正確產生 GET |
| `read_only_policy` | C Semantic／執行器 | methods 只能是 `GET` | 安全邊界 |
| `source_evidence` | 建置與紀錄 | metadata hash、驗證時間、已驗證名稱 | 防止猜測 SAP schema |
| `compiler_version` | 產物 metadata | 非空 | 追蹤編譯行為 |
| `model_sha256` | 產物 metadata | canonical serialization 計算 | 偵測模型 drift |
| `artifact_sha256` | 實驗紀錄 | 對每組產物計算 | 確認 run 使用的工具版本 |

`business_descriptions` 不另建一套全域字典；它們附著在 entity、relationship、operation 與 parameter 上，並由同一模型驗證。這可避免描述和結構分離後產生 drift。

## Agent-visible 與 private binding 邊界

| Agent 可見 | 僅頁面內部可見 |
| --- | --- |
| 工具名稱與用途 | SAP endpoint |
| 允許的參數、型別與格式 | Basic Auth credentials |
| C 組的企業概念與文件關係 | EntitySet／property／association 名稱 |
| read-only 說明 | `$select`、`$filter`、`$expand`、分頁組裝 |
| 正規化 output schema | OData V2 `d.results` 解析與錯誤正規化 |
| model／artifact version | tenant-specific metadata evidence |

## SAP SD 最小語意模型範例草稿

以下是 Phase 02 的輸入草稿，不是可直接發布的 OData binding。只有瀏覽器閘門已證實的 `A_SalesOrder` 與 `SalesOrder` 標成 `tenant_verified`；Delivery、Billing、Customer 相關技術名稱仍須依完整 tenant `$metadata` 核對。

```yaml
model_id: sap-sd-webmcp
model_version: 0.1.0-draft
status: draft

read_only_policy:
  allowed_http_methods: [GET]
  reject_unlisted_operations: true

entities:
  - id: customer
    business_description: Places sales orders.
  - id: sales_order
    business_description: Commercial document recording a customer's order.
  - id: outbound_delivery
    business_description: Logistics document used to fulfill a sales order.
  - id: billing_document
    business_description: Billing document created from the sales process.

relationships:
  - id: customer_places_sales_order
    source: customer
    predicate: places
    target: sales_order
  - id: sales_order_generates_outbound_delivery
    source: sales_order
    predicate: generates
    target: outbound_delivery
  - id: sales_order_generates_billing_document
    source: sales_order
    predicate: generates
    target: billing_document

operations:
  - id: search_sales_orders
    entity: sales_order
    parameters:
      - {id: criteria, type: object, required: true, additional_properties: false}
    output_schema: sales_order_list
    odata_binding: {verification_status: partially_verified}
  - id: get_sales_order
    entity: sales_order
    parameters:
      - {id: sales_order_id, type: string, required: true, format: sap_sales_order_id}
    output_schema: sales_order_detail
    odata_binding:
      verification_status: tenant_verified
      entity_set: A_SalesOrder
      key_property: SalesOrder
  - id: get_related_deliveries
    entity: outbound_delivery
    parameters:
      - {id: sales_order_id, type: string, required: true, format: sap_sales_order_id}
    output_schema: delivery_list
    odata_binding: {verification_status: unverified}
  - id: get_related_billing_documents
    entity: billing_document
    parameters:
      - {id: sales_order_id, type: string, required: true, format: sap_sales_order_id}
    output_schema: billing_document_list
    odata_binding: {verification_status: unverified}

output_schemas:
  sales_order_list:
    type: object
    required: [items, count, trace]
  sales_order_detail:
    type: object
    required: [sales_order, trace]
  delivery_list:
    type: object
    required: [items, count, trace]
  billing_document_list:
    type: object
    required: [items, count, trace]
```

## Phase 02 交接限制

1. Phase 02 可沿用上述分層與治理欄位，但必須重新定義完整參數及 output fields。
2. Delivery、Billing、Customer 的 EntitySet、property、navigation／association 不得從名稱慣例猜測。
3. `$metadata` 是 tenant-specific binding 的權威；外部 README 只能提供候選查詢方向。
4. 三組可見 contract 可不同，但必須編譯回相同 canonical operation、private binding 與 output schema。
5. 模型驗證器應 fail closed：未知欄位、缺少 binding evidence、非 GET method 或未列入的 operation 都不得產生工具。
