# 系統架構與研究邊界

本文件說明已完成之 SAP SD WebMCP 研究系統。現行語意模型以 `semantic_models/sap_sd/model.yaml` 為準（版本 `0.5.0`、狀態 `validated`）；執行期協定為 SAP OData V2。

```text
建置期
semantic_models/sap_sd/model.yaml
       │ multi-source validation + deterministic compile
       ▼
A / B / C tool catalogs + runtime bindings
       │
執行期
ChatGPT／Codex Agent → Browser-native WebMCP tools
                              │
                     Shared Application Actions
                              │ GET only
                    direct browser 或明確選用的
                       localhost Gateway
                              │ HTTPS GET
                       SAP OData V2
```

Semantic Model 只在建置期驗證並編譯工具，不是 Agent 執行期查詢服務。編譯產物記錄模型與 artifact hash，供執行條件追溯。SAP binding 依固定版本的 SAP S/4HANA 2023／S4CORE 108 官方定義、tenant `$metadata`、known-case evidence 與 Semantic Binding Validation 交叉驗證。

## 資料流

1. Agent 依目前條件可見的工具 schema 選擇操作並產生參數。
2. Browser runtime 將公開參數正規化為 canonical business arguments。
3. 共用 Application Actions 驗證 allowlist、格式、長度與必填條件。
4. OData client 依固定 binding 與 transport profile 發出 HTTPS GET。
5. OData V2 回應正規化為共同輸出 schema，並附上模型版本、擷取時間與 request ID。

## 安全邊界

- SAP 操作只允許 HTTP GET；不回退到 mock、舊 endpoint 或其他 OData 版本。
- 帳密和 tenant 設定只在本機環境提供；不寫入公開 tool definition、研究包或版本庫。
- Runtime 對 Agent 只公開受治理的摘要與錯誤，不公開 raw SAP rows、完整 URL 或 credential。
- localhost Gateway 僅是明確選用的受限 transport 相容層，不是業務資料來源或 Agent Controller。

## 研究設計

Study 1 比較 A Technical、B Typed、C Semantic 三種工具描述；20 題、每條件三次重複，共 180 筆有效評分。所有條件共用相同的四個 operation、資料、執行層、網站狀態與評分規則，只改變 Agent 可見的工具名稱、描述及參數語意。

Study 2 是獨立的受限額度補充研究；12 題、每條件兩次重複，共 72 筆有效評分。除共用的 A/B/C 條件外，依任務難度分別設定 1、2、3 次工具呼叫額度。兩項研究分開報告分母及統計分析，不合併樣本。

Phase 07 pilot 是方法開發紀錄，不納入上述兩項研究結果。Study 1 的受控 120 秒逾時中斷證據已由研究者豁免，因此本研究不宣稱已驗證執行期逾時控制；工具呼叫上限由離線評分判定。
