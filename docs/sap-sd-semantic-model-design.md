# SAP SD 最小語意模型設計

## 文件定位

本文件是現行 SAP SD 語意模型的說明文件。機器可讀契約以 `semantic_models/sap_sd/model.yaml` 為準（版本 `0.5.0`、狀態 `validated`）；本文件說明四個 canonical operations、輸入／輸出契約、已驗證的 OData binding 與治理規則，不是可直接註冊或執行的 WebMCP tool definition。

本設計遵守下列固定邊界：

- 只支援 `search_sales_orders`、`get_sales_order`、`get_related_deliveries`、`get_related_billing_documents`。
- SAP runtime source 是目標 tenant 的 OData V2；`semantic_analytics` 只提供設計參考，不是 runtime dependency 或 fallback。
- 執行只允許 HTTP GET，不允許寫入、proxy、mock、其他 endpoint 或 OData 版本的 silent fallback。
- Agent-visible contract 不包含 endpoint、credential、EntitySet、property、OData query 或 raw SAP row。
- A／B／C 三組必須正規化成相同 canonical operation、canonical arguments、private binding 與 output schema。

### Scope boundary

本研究不建立完整 SAP SD 模組之通用語意模型，而僅針對實驗情境所涉及之 Sales Order、
Outbound Delivery、Billing Document 與文件流關聯欄位進行語意綁定與狀態碼治理。
因此本模型不涵蓋完整 SAP SD ontology、所有 table、所有 fixed values 或全面 reverse
engineering。這是可支援特定跨文件任務的 semantic layer，不是 SAP SD 通用知識庫。

研究所需欄位固定收斂為：

| Business concept | SAP property | Code-list governance |
| --- | --- | --- |
| Sales order status | `OverallSDProcessStatus` | required |
| Delivery status | `OverallGoodsMovementStatus` | required |
| Billing/accounting status | `AccountingPostingStatus` | required |
| Document-flow discriminator | `SubsequentDocumentCategory` | required |
| Customer、date、document ID | tenant-verified property | not required |

只有 enumeration、status、category、discriminator 類型欄位需要 code-list；一般 ID、date、
quantity、customer 欄位只驗證 property、EDM type 與長度。

## 模型識別與生命週期

| 欄位 | 值 | 規則 |
| --- | --- | --- |
| `model_id` | `sap-sd-webmcp` | 穩定且不可因實驗條件改名。 |
| `model_version` | `0.5.0` | 與目前已驗證的機器可讀模型一致；語意或契約變更必須遞增。 |
| `status` | `validated` | 已通過 Phase 03 multi-source strict gate。 |
| `protocol` | `odata-v2` | 不自動 fallback 到 V4。 |
| `source_id` | `webmcp.sap_sd.odata` | live SAP source；authority 是 tenant `$metadata`。 |
| `model_source_id` | `webmcp.sap_sd.semantic_model` | 本文件所治理的 semantic model source。 |

## 企業實體

| Entity ID | 業務名稱 | Business description | 支援操作／任務 | 主要評估用途 |
| --- | --- | --- | --- | --- |
| `customer` | 客戶 | 向企業提出銷售需求並擁有相關銷售訂單的業務對象。 | `search_sales_orders`；D1、D3 | Parameter Accuracy：客戶搜尋條件。 |
| `sales_order` | 銷售訂單 | 記錄客戶訂購內容，並作為後續交貨及請款追蹤起點的商業文件。 | `search_sales_orders`、`get_sales_order`、兩項 related operations；D1、D2、D3 | Tool Selection、Parameter Accuracy、Task Success。 |
| `outbound_delivery` | 外向交貨 | 為履行銷售訂單而建立、可由來源訂單追蹤的物流文件。 | `get_related_deliveries`；D2、D3 | Tool Selection、Task Success。 |
| `billing_document` | 請款文件 | 銷售流程中產生、可由來源訂單追蹤的請款文件。 | `get_related_billing_documents`；D2、D3 | Tool Selection、Task Success。 |

`customer` 是模型概念與訂單搜尋條件，不新增 customer lookup tool。四工具仍為封閉集合。

## 文件關係

| Relationship ID | Source | Predicate | Target | 方向與業務意義 | 支援操作／任務 |
| --- | --- | --- | --- | --- | --- |
| `customer_places_sales_order` | `customer` | `places` | `sales_order` | 由客戶理解其所屬銷售訂單；查詢時以客戶條件搜尋訂單。 | `search_sales_orders`；D1、D3 |
| `sales_order_generates_outbound_delivery` | `sales_order` | `generates` | `outbound_delivery` | 由已知銷售訂單追蹤為履約所產生的外向交貨。 | `get_related_deliveries`；D2、D3 |
| `sales_order_generates_billing_document` | `sales_order` | `generates` | `billing_document` | 由已知銷售訂單追蹤銷售流程產生的請款文件。 | `get_related_billing_documents`；D2、D3 |

關係只描述本研究固定的業務查詢方向，不代表 OData navigation 已存在。association、navigation 或跨 service filter 必須由 tenant `$metadata` 與唯讀 GET 實測另行證實。

## Canonical operations

### `search_sales_orders`

| 欄位 | 定義 |
| --- | --- |
| 業務目的 | 依允許的業務條件搜尋銷售訂單，提供 D1 結果或 D3 的後續文件追蹤起點。 |
| 適用情境 | 使用者尚未提供唯一銷售訂單識別碼，而是提供客戶、訂單日期範圍或訂單狀態。 |
| 不適用情境 | 已知唯一訂單識別碼時應使用 `get_sales_order`；不得用來任意查詢未列入 allowlist 的 SAP 欄位。 |
| HTTP policy | GET only。 |
| Input | `criteria`，required object，`additionalProperties: false`。 |
| Cross-field rule | `criteria` 至少提供一個非空條件；`order_date_from` 不得晚於 `order_date_to`。 |
| Output | `sales_order_list`。 |

`criteria` 欄位：

| Parameter ID | 業務名稱與意義 | 型別 | 格式／長度 | 必填 | 驗證狀態 | 支援指標 |
| --- | --- | --- | --- | --- | --- | --- |
| `customer_id` | 客戶識別碼；只搜尋該客戶的訂單。 | string | `sap_customer_id`；MaxLength 10。 | 否 | `SoldToParty` tenant metadata 與 filter smoke 已驗證 | Parameter Accuracy |
| `order_date_from` | 訂單日期區間起點，包含當日。 | string | RFC 3339 `full-date`（`YYYY-MM-DD`）。 | 否 | `SalesOrderDate` tenant metadata 與 filter smoke 已驗證 | Parameter Accuracy |
| `order_date_to` | 訂單日期區間終點，包含當日。 | string | RFC 3339 `full-date`（`YYYY-MM-DD`）。 | 否 | `SalesOrderDate` tenant metadata 與 filter smoke 已驗證 | Parameter Accuracy |
| `order_status` | 訂單業務狀態；只允許模型明列並完成 SAP code mapping 的值。 | string | `not_started`／`partially_completed`／`completed`。 | 否 | 官方 A/B/C domain 與 tenant C → completed representative case 已確認 | Parameter Accuracy |

分頁、`$top`、`$select`、OData literal escaping 與結果上限是 private execution policy，不是 Agent-visible 參數。

### `get_sales_order`

| 欄位 | 定義 |
| --- | --- |
| 業務目的 | 以唯一識別碼取得單筆銷售訂單，供 D1 回答或 D2／D3 的確認步驟。 |
| 適用情境 | 使用者或目前頁面狀態已有唯一銷售訂單識別碼。 |
| Input | `sales_order_id`。 |
| HTTP policy | GET only。 |
| Output | `sales_order_detail`。 |

| Parameter ID | 業務名稱與意義 | 型別 | 格式／長度 | 必填 | 驗證狀態 | 支援指標 |
| --- | --- | --- | --- | --- | --- | --- |
| `sales_order_id` | 要取得的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；MaxLength 10。 | 是 | `SalesOrder` property、型別、長度與唯一 filter 已驗證 | Parameter Accuracy、Task Success |

### `get_related_deliveries`

| 欄位 | 定義 |
| --- | --- |
| 業務目的 | 從已知銷售訂單追蹤所有相關外向交貨。 |
| 適用情境 | D2 或 D3 任務要求交貨文件、交貨狀態或是否存在交貨。 |
| Input | `sales_order_id`。 |
| HTTP policy | GET only。 |
| Output | `delivery_list`。 |

| Parameter ID | 業務名稱與意義 | 型別 | 格式／長度 | 必填 | 驗證狀態 | 支援指標 |
| --- | --- | --- | --- | --- | --- | --- |
| `sales_order_id` | 作為文件流程起點的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；MaxLength 10。 | 是 | item document flow 與 category J known case 已驗證 | Parameter Accuracy、Task Success |

### `get_related_billing_documents`

| 欄位 | 定義 |
| --- | --- |
| 業務目的 | 從已知銷售訂單追蹤所有相關請款文件。 |
| 適用情境 | D2 或 D3 任務要求請款文件、請款狀態或是否存在請款。 |
| Input | `sales_order_id`。 |
| HTTP policy | GET only。 |
| Output | `billing_document_list`。 |

| Parameter ID | 業務名稱與意義 | 型別 | 格式／長度 | 必填 | 驗證狀態 | 支援指標 |
| --- | --- | --- | --- | --- | --- | --- |
| `sales_order_id` | 作為文件流程起點的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；MaxLength 10。 | 是 | item document flow 與 category M known case 已驗證 | Parameter Accuracy、Task Success |

## Delivery 與 Billing 正式業務欄位定義

下列定義是 public semantic contract。列出的 SAP property 已依 SAP S/4HANA 2023 官方 API、tenant metadata、唯讀 GET 與 known-case business cross-check 驗證；status code 的完整範圍由官方定義治理，tenant cases 用來確認代表性語意。

| Semantic field | 正式定義 | SAP property | 邊界 |
| --- | --- | --- | --- |
| `delivery_date` | Outbound Delivery 完成 Post Goods Issue 時，SAP 記錄的實際貨物移動日期。 | `ActualGoodsMovementDate` | 代表系統中的實際出貨事件，不推定法律上的所有權移轉時間。 |
| `delivery_status` | Outbound Delivery 表頭層級的整體貨物移動處理狀態，用以判斷 PGI 是否尚未開始、部分完成或完成。 | `OverallGoodsMovementStatus` | 官方定義提供 code domain，代表性 tenant cases 已交叉驗證；不自行擴張 code 語意。 |
| `billing_date` | Billing Document 的業務文件日期。 | `BillingDocumentDate` | 不以技術建立日期替代，也不推定為應收帳款付款基準日。 |
| `billing_status` | Billing Document 向財務會計移轉及產生相關會計文件的處理狀態。 | `AccountingPostingStatus` | STATV domain 已通過 strict reconciliation；不代表應收帳款已完成收款或清帳。 |

Delivery 與 Billing 使用各自明確的 OData V2 service selector，不以 Sales Order service 的同名
欄位替代，也不在 service 間 silent fallback。

## Canonical output schemas

所有 operation 都回傳 tenant-neutral structured result。欄位必須固定存在；SAP 未提供或不適用時使用 `null`，不得臨時把 raw property 加入 response。

### 共用 `trace`

| Field | 型別 | 必填 | 用途 |
| --- | --- | --- | --- |
| `request_id` | string | 是 | 串接工具呼叫、頁面狀態與實驗紀錄。 |
| `operation_id` | string enum | 是 | Tool Selection Accuracy 與 canonical trace。 |
| `model_id` | string | 是 | 模型追溯。 |
| `model_version` | string | 是 | 模型版本追溯。 |
| `protocol` | string enum：`odata-v2` | 是 | 證明未發生協定 fallback。 |
| `retrieved_at` | RFC 3339 date-time string | 是 | 記錄 live source 擷取時間。 |
| `source_evidence_id` | string | 是 | 連結建置時使用的 sanitized metadata evidence。 |

### `sales_order_summary`

| Field | 型別 | 必填 | 支援操作／任務／指標 |
| --- | --- | --- | --- |
| `sales_order_id` | string | 是 | 搜尋選取、單筆查詢、D1／D3、Parameter Accuracy、Task Success。 |
| `customer_id` | string or null | 是 | 客戶條件核對、D1／D3、Task Success。 |
| `order_date` | full-date string or null | 是 | 日期條件核對、D1／D3、Task Success。 |
| `order_status` | governed enum string or null | 是 | 狀態條件核對、D1／D3、Task Success。 |

### `delivery_summary`

| Field | 型別 | 必填 | 支援操作／任務／指標 |
| --- | --- | --- | --- |
| `delivery_id` | string | 是 | 識別 Ground Truth 所需交貨文件、D2／D3、Task Success。 |
| `sales_order_id` | string | 是 | 證明結果屬於輸入訂單、D2／D3、Task Success。 |
| `delivery_date` | full-date string or null | 是 | 回答交貨時間類任務、Task Success。 |
| `delivery_status` | governed enum string or null | 是 | 回答交貨狀態類任務、Task Success。 |

### `billing_document_summary`

| Field | 型別 | 必填 | 支援操作／任務／指標 |
| --- | --- | --- | --- |
| `billing_document_id` | string | 是 | 識別 Ground Truth 所需請款文件、D2／D3、Task Success。 |
| `sales_order_id` | string | 是 | 證明結果屬於輸入訂單、D2／D3、Task Success。 |
| `billing_date` | full-date string or null | 是 | 回答請款時間類任務、Task Success。 |
| `billing_status` | governed enum string or null | 是 | 回答請款狀態類任務、Task Success。 |

### Operation envelopes

| Output schema ID | 結構 | 使用者 |
| --- | --- | --- |
| `sales_order_list` | `{ items: sales_order_summary[], count: integer, trace: trace }` | `search_sales_orders` |
| `sales_order_detail` | `{ sales_order: sales_order_summary or null, trace: trace }` | `get_sales_order` |
| `delivery_list` | `{ items: delivery_summary[], count: integer, trace: trace }` | `get_related_deliveries` |
| `billing_document_list` | `{ items: billing_document_summary[], count: integer, trace: trace }` | `get_related_billing_documents` |

`count` 是本次正規化結果陣列長度，不宣稱是 SAP 端未分頁的全資料總數。空結果以空陣列和 `count: 0` 表示；單筆不存在以 `sales_order: null` 表示。錯誤必須走 Phase 06 定義的共用 error contract，不得以 raw OData error 代替業務輸出。

## 已驗證的 OData binding

### Operation binding

| Operation | Symbolic service | EntitySet／查詢方式 | 關鍵 property／關聯 | Evidence status |
| --- | --- | --- | --- | --- |
| `search_sales_orders` | `sales_order_service` | `A_SalesOrder` collection GET/filter | `SalesOrder`、`SoldToParty`、`SalesOrderDate`、`OverallSDProcessStatus` | `tenant_verified` binding；完整狀態 domain 依官方定義治理 |
| `get_sales_order` | `sales_order_service` | `A_SalesOrder` unique filter | `SalesOrder` | `tenant_verified` |
| `get_related_deliveries` | Sales Order flow + Delivery enrichment | `A_SalesOrderItmSubsqntProcFlow` filter，再查 `A_OutbDeliveryHeader` | category J、document ID、日期、status | `tenant_verified` |
| `get_related_billing_documents` | Sales Order flow + Billing enrichment | `A_SalesOrderItmSubsqntProcFlow` filter，再查 `A_BillingDocument` | category M、document ID、日期、status | `tenant_verified`；`STATV` domain 依官方定義治理 |

Tenant evidence 已證明 `A_SalesOrder`、`A_SalesOrderItmSubsqntProcFlow`、
`SalesOrder`、`SubsequentDocument` 與 `SubsequentDocumentCategory` 的實際查詢路徑，並由兩項
known-case 確認 `J = outbound_delivery`、`R = other`、`M = billing_document`。Delivery 與
Billing service 的 document-level metadata／GET cross-check 另已確認四個候選欄位；Delivery
已有 A/C representative cases、Billing 已有 C case。完整 domain 由固定版本的 SAP 官方
定義與 tenant SAP DDIC `STATV` value range 對齊；不能用 tenant 未出現某個值推論該值不存在。

### Output field mapping

| Business field | SAP property | Evidence status | 發布規則 |
| --- | --- | --- | --- |
| `sales_order_id` | `SalesOrder` | `tenant_verified` | `Edm.String(10)`。 |
| `customer_id` | `SoldToParty` | `tenant_verified` | `Edm.String(10)`。 |
| `order_date` | `SalesOrderDate` | `tenant_verified` | `Edm.DateTime` 正規化為 full-date。 |
| `order_status` | `OverallSDProcessStatus` | `tenant_verified` binding | A/B/C domain 依官方定義治理；tenant observed C。 |
| `delivery_id` | `SubsequentDocument` | `tenant_verified` | category J known case；`Edm.String(10)`。 |
| `delivery_date` | `ActualGoodsMovementDate` | `tenant_verified` | Delivery enrichment metadata 與 known case 已核對。 |
| `delivery_status` | `OverallGoodsMovementStatus` | `tenant_verified` | 官方 A/B/C；tenant observed A/C。 |
| `billing_document_id` | `SubsequentDocument` | `tenant_verified` | category M known case；`Edm.String(10)`。 |
| `billing_date` | `BillingDocumentDate` | `tenant_verified` | Billing enrichment metadata 與 known case 已核對。 |
| `billing_status` | `AccountingPostingStatus` | `tenant_verified` binding | SAP DDIC domain STATV：空白／A／B／C；tenant observed C。Semantic value 使用 `completely_processed`，不直接把 SAP 原文改寫成 `posted`。 |

## Source evidence 規格

模型採 multi-source validation，固定版本基準為 SAP S/4HANA 2023 / S4CORE 108：官方 API
定義提供 service/property 與完整 code domain，tenant `$metadata` 提供實際 type/length/hash，
known-case runtime evidence 提供 representative semantic values，最後才執行 Semantic Binding
Validation。Sales Order、document-flow、Delivery enrichment 與 Billing enrichment 的 binding
evidence 已完成；Sales Order status 與 Billing STATV domain 均已通過 strict reconciliation。

驗證 evidence 使用下列可追溯欄位：

- 穩定的 `source_evidence_id`。
- `source_id: webmcp.sap_sd.odata`。
- OData service 的 symbolic ID，不含 tenant endpoint。
- OData version、驗證時間與完整 metadata SHA-256。
- 本模型實際使用的 EntitySet、property、key、EDM type、length、association/navigation 摘要。
- 每個 binding 的 `tenant_verified`、`partially_verified` 或 `unverified` 狀態。
- GET/filter smoke-test 結果摘要；不得保存 business key、raw row 或 raw metadata。

若未來新增 Delivery 或 Billing 以外的 SAP service，必須先更新 `.env.example` 的 credential-free selector、資料來源目錄與 browser connectivity gate；不得把其他服務硬編碼成 fallback。

## Read-only 與 fail-closed policy

1. `allowed_http_methods` 只能包含 `GET`。
2. 未列入四個 canonical operations 的操作一律拒絕。
3. 未列入參數 schema 的欄位一律拒絕。
4. 未驗證或 evidence hash 不符的 binding 不得編譯成 active tool。
5. 只接受已納入 `model.yaml` 並通過驗證的 status code mapping；不得回傳臨時翻譯值。
6. 不得把 synthetic fixture、ground truth、其他 SAP adapter、舊 endpoint 或不同 OData 版本當成 fallback。
7. Agent-visible artifact 不得包含 private binding 或 sensitive configuration。

## 驗證狀態

| 模型項目 | 現行證據 | 狀態 |
| --- | --- | --- |
| 四個 entity 與文件關係 | 企業實體、文件關係 | 已納入模型 |
| 四個操作與參數契約 | Canonical operations | 已納入模型並通過驗證 |
| 輸出欄位與 trace | Canonical output schemas | 已納入模型並通過驗證 |
| SAP bindings 與狀態碼 | 已驗證的 OData binding、Source evidence | 多來源 evidence 已核對 |
| 唯讀與 fail-closed policy | Read-only 與 fail-closed policy | 僅允許 GET；拒絕未驗證 binding |

目前模型為 `0.5.0` 且狀態為 `validated`。後續如需變更語意、binding 或公開契約，應更新機器可讀模型、重新驗證並升版；本說明文件需同步反映核准後的模型內容。
