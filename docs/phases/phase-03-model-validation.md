# Phase 3：Multi-source Semantic Binding Validation

## 版本基準與 evidence policy

本階段固定對應 **SAP S/4HANA 2023 / S4CORE 108**，不混用其他 SAP release 的定義。
模型使用下列明確 precedence：

```text
SAP S/4HANA 2023 官方 API 定義
              ↓
tenant $metadata（S4CORE 108）
              ↓
known-case runtime evidence
              ↓
Semantic Binding Validation
```

- 官方 evidence：`semantic_models/sap_sd/evidence/official-s4hana-2023.json`
- Tenant evidence：`semantic_models/sap_sd/evidence/tenant-binding-evidence.json`
- Canonical model：`semantic_models/sap_sd/model.yaml`（`0.3.0`，`validated`）
- JSON Schema：`semantic_models/sap_sd/model.schema.json`
- Executable validator：`src/semantic_model/validator.py`

官方 API 定義負責 service、operation、EntitySet/property coverage 與完整 status domain；tenant
`$metadata` 負責實際可用的 property、EDM type、MaxLength 與 metadata hash；known case 負責
tenant 中代表性值的業務語意。三層任一缺失或互相矛盾，strict gate 都必須 fail closed。

研究 scope 僅涵蓋 Sales Order、Outbound Delivery、Billing Document 與 document-flow 關聯欄位。
Code-list 只套用於 status／enumeration／category／discriminator；一般 ID、date、quantity、
customer 欄位不要求 code-list。

## 五層 evidence 狀態

| 層次 | 所需 evidence | 目前狀態 |
| --- | --- | --- |
| Sales Order binding | 2023 官方 API、tenant metadata、collection/filter smoke | Binding、property/type/length 與 `OverallSDProcessStatus = C → completed` tenant case 已 `tenant_verified`。 |
| Document-flow discriminator | tenant known cases | `J = outbound_delivery`、`R = other`、`M = billing_document` 已 `tenant_verified`。 |
| Delivery enrichment | 2023 官方 API、tenant metadata、既有 A/C cases | 欄位與 enrichment 已 `tenant_verified`；A/C tenant observed，B 僅 `official_documented`，不要求製造 tenant case。 |
| Billing enrichment | 2023 官方 API、tenant metadata、既有 C case | 欄位與 enrichment 已 `tenant_verified`；C tenant observed。 |
| Status code map | 完整官方 domain、tenant representative values | Sales Order、Delivery、Billing 的研究範圍 domain 已納管；Billing 使用 STATV 空白/A/B/C，tenant 目前觀察 C。 |

Status map 的規則是「完整 domain 由官方文件/code-list 提供，representative values 由 tenant
observed」。validator 不要求 tenant 出現 domain 每一個值，因此 Delivery B 可以保持
`official_documented`；它也不允許以單一 tenant C case 冒充完整 Billing domain。

## Validator 行為

Draft validation 檢查 schema、引用、GET-only policy、release baseline、官方 API/property coverage、
tenant metadata 一致性與已宣告 evidence 的互相一致。Strict compilation gate 另外要求：

- 模型生命週期為 `validated`；
- binding、discriminator、enrichment 與 field 都是 `tenant_verified`；
- Sales Order metadata/collection/filter smoke 全部通過；
- document-flow category 有 tenant known case；
- Delivery/Billing enrichment 有成功的 representative tenant case；
- 每個 status domain 都有完整的 SAP 官方 code-list；
- 至少一個 tenant-observed representative value，且語意不和官方 domain 衝突。

Related operation 是 composite binding：先從 Sales Order item document flow 取得 downstream
document/category，再用 document ID 對 Delivery 或 Billing service 做唯一 GET enrichment。
兩段都只能 GET，且各自 pin sanitized metadata SHA-256。

## 驗證命令

```powershell
uv run python -m pytest -q

uv run python -m semantic_model.cli validate `
  --model semantic_models\sap_sd\model.yaml `
  --evidence semantic_models\sap_sd\evidence\tenant-binding-evidence.json `
  --official-evidence semantic_models\sap_sd\evidence\official-s4hana-2023.json `
  --schema semantic_models\sap_sd\model.schema.json `
  --allow-draft `
  --report build\phase-03-validation-report.json
```

Phase 04 使用同一命令但移除 `--allow-draft`；五層 evidence 完成後必須取得零 issue 才能交給 compiler。

## Sanitized tenant evidence

Browser probe 直接從 Chrome 對 tenant 發送 OData V2 GET，只保存：symbolic service ID、
EntitySet/property/type/length 摘要、metadata SHA-256、smoke 結果、status code 的受控業務分類與
確認時間。不得保存 endpoint、credential、business key、raw metadata、raw row 或完整 error。

- `scripts/browser_sap_probe.py` v3.5：Sales Order metadata/smoke、status representative cases 與 document-flow known cases。
- `scripts/browser_sap_field_probe.py`：Delivery/Billing metadata、唯一 GET 與 status known cases。
- `.env` 中的 service root 是唯一 selector；不得回退到 proxy、V4、mock 或其他 SAP adapter。

## 已驗證結果

- 67 個正向／負向測試通過。
- Draft multi-source validation exit code 為 `0`，issues 為空。
- Canonical model SHA-256：`25edfd5a5afeefd88f56bf3247c58918ce234b34a09a3af65e27980301b898d3`。
- Strict compilation gate exit code 為 `0`，`issues` 為空，`compilation_ready` 為 `true`。
- Model status 已由 `draft` 升級為 `validated`；Phase 03 evidence gate 已關閉。

## 通過條件

五層 evidence 都通過 multi-source reconciliation、模型狀態為 `validated`，且 strict gate
無 issue，才可交給 Phase 04 compiler。Synthetic fixture 只證明 validator 規則，不是 tenant
runtime evidence。
