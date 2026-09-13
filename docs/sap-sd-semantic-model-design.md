# SAP SD 最小語意模型設計

## 文件定位

本文件是 Phase 02 的 canonical 設計產物，定義 SAP SD 跨文件查詢原型的企業語意、四個 canonical operations、輸入／輸出契約、private OData binding 候選及治理規則。它是 Phase 03 機器可讀模型與 validator 的輸入，不是可直接註冊或執行的 WebMCP tool definition。

本設計遵守下列固定邊界：

- 只支援 `search_sales_orders`、`get_sales_order`、`get_related_deliveries`、`get_related_billing_documents`。
- SAP runtime source 是目標 tenant 的 OData V2；`semantic_analytics` 只提供設計參考，不是 runtime dependency 或 fallback。
- 執行只允許 HTTP GET，不允許寫入、proxy、mock、其他 endpoint 或 OData 版本的 silent fallback。
- Agent-visible contract 不包含 endpoint、credential、EntitySet、property、OData query 或 raw SAP row。
- A／B／C 三組必須正規化成相同 canonical operation、canonical arguments、private binding 與 output schema。

## 模型識別與生命週期

| 欄位 | 值 | 規則 |
| --- | --- | --- |
| `model_id` | `sap-sd-webmcp` | 穩定且不可因實驗條件改名。 |
| `model_version` | `0.2.0-draft` | Phase 02 設計版；語意或契約變更必須遞增。 |
| `status` | `draft` | Phase 03 validation 通過前不得標成 `validated` 或 `active`。 |
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
| `customer_id` | 客戶識別碼；只搜尋該客戶的訂單。 | string | `sap_customer_id`；實際最大長度由 metadata 決定，Phase 03 前須補證據。 | 否 | OData property 未驗證 | Parameter Accuracy |
| `order_date_from` | 訂單日期區間起點，包含當日。 | string | RFC 3339 `full-date`（`YYYY-MM-DD`）。 | 否 | OData property／literal encoding 未驗證 | Parameter Accuracy |
| `order_date_to` | 訂單日期區間終點，包含當日。 | string | RFC 3339 `full-date`（`YYYY-MM-DD`）。 | 否 | OData property／literal encoding 未驗證 | Parameter Accuracy |
| `order_status` | 訂單業務狀態；只允許模型明列並完成 SAP code mapping 的值。 | string | governed enum；目前 allowlist 尚未由 tenant evidence 封閉。 | 否 | OData property／code mapping 未驗證 | Parameter Accuracy |

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
| `sales_order_id` | 要取得的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；實際最大長度由 metadata 決定。 | 是 | `SalesOrder` property 名稱已驗證；型別／長度尚待保存 evidence | Parameter Accuracy、Task Success |

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
| `sales_order_id` | 作為文件流程起點的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；實際最大長度由 metadata 決定。 | 是 | Delivery 關聯 property／association 未驗證 | Parameter Accuracy、Task Success |

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
| `sales_order_id` | 作為文件流程起點的銷售訂單識別碼。 | string | `sap_sales_order_id`；non-empty；實際最大長度由 metadata 決定。 | 是 | Billing 關聯 property／association 未驗證 | Parameter Accuracy、Task Success |

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

## Private OData binding 候選

### Operation binding

| Operation | Symbolic service | EntitySet／查詢方式 | 關鍵 property／關聯 | Evidence status | 下一個證據動作 |
| --- | --- | --- | --- | --- | --- |
| `search_sales_orders` | `sales_order_service` | `A_SalesOrder` collection GET | `SalesOrder` 已驗證；Customer、date、status properties 未驗證 | `partially_verified` | 從同一份 tenant `$metadata` 核對 property type／length，並逐一執行無敏感紀錄的 filter smoke test。 |
| `get_sales_order` | `sales_order_service` | `A_SalesOrder` collection GET with unique filter；是否能用 canonical key path 尚待核對 | `SalesOrder` | `partially_verified` | 保存 property type／length/key evidence；驗證唯一結果與 not-found 行為。 |
| `get_related_deliveries` | `delivery_service_unresolved` | 未驗證 | 未驗證 | `unverified` | 確認目前 service 是否提供 association/navigation；若需另一個已啟用 service，先建立明確 runtime selector 再驗證。 |
| `get_related_billing_documents` | `billing_service_unresolved` | 未驗證 | 未驗證 | `unverified` | 確認目前 service 是否提供 association/navigation；若需另一個已啟用 service，先建立明確 runtime selector 再驗證。 |

`A_SalesOrder` 與 `SalesOrder` 是目前唯一可寫成 tenant-verified name 的技術 mapping。其他名稱不得從 SAP 文件、命名慣例、其他 repository 或模型記憶推定。

### Output field mapping

| Business field | Candidate SAP property | Evidence status | 發布規則 |
| --- | --- | --- | --- |
| `sales_order_id` | `SalesOrder` | `tenant_verified_name` | 補齊 EDM type／length evidence 後才可進入 validated model。 |
| `customer_id` | 未指定 | `unverified` | 從 tenant metadata 核對後填入。 |
| `order_date` | 未指定 | `unverified` | 核對 EDM date/time type 與 V2 normalization 後填入。 |
| `order_status` | 未指定 | `unverified` | property 與 code-to-business enum mapping 均須有證據。 |
| `delivery_id` | 未指定 | `unverified` | 核對 EntitySet、key、來源訂單關聯後填入。 |
| `delivery_date` | 未指定 | `unverified` | 核對 property type 與 normalization 後填入。 |
| `delivery_status` | 未指定 | `unverified` | property 與 code mapping 均須有證據。 |
| `billing_document_id` | 未指定 | `unverified` | 核對 EntitySet、key、來源訂單關聯後填入。 |
| `billing_date` | 未指定 | `unverified` | 核對 property type 與 normalization 後填入。 |
| `billing_status` | 未指定 | `unverified` | property 與 code mapping 均須有證據。 |

## Source evidence 規格

Phase 01 已證實：目標瀏覽器可直接讀取 OData V2 `$metadata`，service 有 22 個 EntitySets，`A_SalesOrder` 包含 `SalesOrder`，EntitySet GET 及以 `SalesOrder` 等值過濾的 GET 均成功。Phase 01 repository 記錄沒有保存完整 metadata hash、EDM type、MaxLength、key、navigation 或 association 摘要，因此本模型不能把這些細節提升為已驗證事實。

Phase 03 建立 machine-readable evidence 時，每筆 evidence 最少包含：

- 穩定的 `source_evidence_id`。
- `source_id: webmcp.sap_sd.odata`。
- OData service 的 symbolic ID，不含 tenant endpoint。
- OData version、驗證時間與完整 metadata SHA-256。
- 本模型實際使用的 EntitySet、property、key、EDM type、length、association/navigation 摘要。
- 每個 binding 的 `tenant_verified`、`partially_verified` 或 `unverified` 狀態。
- GET/filter smoke-test 結果摘要；不得保存 business key、raw row 或 raw metadata。

若 Delivery 或 Billing 需要新的 SAP service，必須先更新 `.env.example` 的 credential-free selector、資料來源目錄與 browser connectivity gate；不得把其他服務硬編碼成 fallback。

## Read-only 與 fail-closed policy

1. `allowed_http_methods` 只能包含 `GET`。
2. 未列入四個 canonical operations 的操作一律拒絕。
3. 未列入參數 schema 的欄位一律拒絕。
4. 未驗證或 evidence hash 不符的 binding 不得編譯成 active tool。
5. status enum 尚未建立受治理 SAP code mapping 時，不得接受 status filter 或回傳臨時翻譯值。
6. 不得把 synthetic fixture、ground truth、其他 SAP adapter、舊 endpoint 或不同 OData 版本當成 fallback。
7. Agent-visible artifact 不得包含 private binding 或 sensitive configuration。

## Phase 03 交接與完成矩陣

| Phase 02 要求 | 本文件證據 | 狀態 |
| --- | --- | --- |
| 四個 entity 的業務描述 | 企業實體 | 完成 |
| 訂單、交貨、請款關係 | 文件關係 | 完成 |
| 四個操作用途與適用情境 | Canonical operations | 完成 |
| 參數名稱、型別、格式、必填 | 各 operation parameter table | 完成；metadata-derived length／enum 明示為 Phase 03 evidence gate |
| 輸出欄位 | Canonical output schemas | 完成 |
| OData binding 候選映射 | Private OData binding 候選 | 完成；未證實項目保持 `unverified` |
| `$metadata` 後續執行前檢查 | Source evidence 規格、fail-closed policy | 完成 |
| 每個欄位可追溯至工具、任務或指標 | entity、parameter、output coverage columns | 完成 |

Phase 03 不得把本文件中的 unresolved item 靜默補值。只有完成 tenant evidence、通過正負向 validation 並產生 canonical model hash 後，模型狀態才能由 `draft` 轉為 `validated`。
