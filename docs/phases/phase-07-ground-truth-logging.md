# Phase 07：Ground Truth、Execution Trace 與離線評分

## 目的

本階段不建立完整實驗平台，而是證明正式 A/B/C 比較所需的 Ground Truth、execution trace 與 scorer 已經可靠。Ground Truth 與 Agent execution 必須分離；Agent、WebMCP catalog 與 runtime 均不得讀取 Ground Truth。

## 五筆 Pilot

Pilot 固定為一筆 D1、兩筆 D2 與兩筆 D3：

| Task | 難度 | 任務形狀 |
| --- | --- | --- |
| P01 | D1 | 單一步驟的已知訂單或條件式單文件查詢 |
| P02 | D2 | 已知訂單下的交貨文件查詢 |
| P03 | D2 | 已知訂單下的請款或交貨加請款查詢 |
| P04 | D3 | 先依條件定位訂單，再追蹤一類下游文件 |
| P05 | D3 | 先依條件定位訂單，再追蹤交貨與請款 |

D1 為單一步驟查詢；D2 為已知業務文件下的跨文件查詢；D3 則需先依條件定位業務文件，再進行跨文件追蹤。案例只能由明確選定的實際 SAP OData V2 tenant 建立，不得用 fixture、mock、其他 SAP adapter 或推測值補足。

本 pilot 採 `human_only` review protocol：Ground Truth 由研究者依 SAP 實際資料逐項確認並核准，不執行 LLM 輔助複核。CLI 仍保留 `human_plus_llm` protocol 供未來研究使用，但每份 corpus 必須在建立時固定單一 protocol，正式執行前固定 approved revision。

Ground Truth 只描述 `expected_outcome`、不限定順序的 `required_operations`、`expected_parameters` 與預先指定的 `task_relevant_parameters`。它不保存唯一正確的 execution sequence。Optional operations、重複呼叫及 retry 上限屬於獨立 scoring policy。

## Execution Trace

瀏覽器以相同的 instrumentation 記錄 A/B/C Agent 呼叫：

- tool name、canonical operation、canonical parameters 與呼叫順序；
- success／failure、duration、sanitized error 與結果摘要；
- 執行前後的 selected order、結果筆數、文件節點及錯誤區域；
- run、task、condition、repetition、model 與 runtime identity。

本機 logger 以 append-only JSONL 保存事件；SAP 文件識別碼在持久化前使用 HMAC 代碼化，raw rows、endpoint、credential 與完整 SAP error payload 不會寫入紀錄。每個完成的檔案以 file SHA-256 固定版本，不加入 per-event hash chain。Logging POST 是本機研究紀錄通道，不改變 SAP GET-only 政策。

## 離線評分

- **Tool Selection Accuracy**：正確工具決策數除以已執行且可評分的工具決策數。它衡量已做決策的正確程度；必要工具是否完整由 Task Success 判定。
- **Parameter Accuracy**：Ground Truth 在執行前指定的 canonical task-relevant parameter values 中，正確值所占比例。
- **Task Success**：所有必要 operation 以正確參數成功執行，且 Agent 最終 reported outcome 包含 Ground Truth 的必要結果時為 1，否則為 0。

Scorer 區分 `tool_selection_error`、`parameter_error`、`sap_query_error` 與 `answer_synthesis_error`。缺少事件、run identity 不一致或紀錄損壞屬於實驗程序無效，不歸因為 Agent 錯誤。

## 實作介面

`phase07-experiment` 提供 corpus validation、HMAC sealing、人工確認、review packet 匯出、LLM review 匯入、研究者核准、log verification 與 run scoring。Phase 07 server 由 run manifest 固定 task、condition、repetition、transport 與 Agent 設定，再使用 Phase 06 的同一 frontend、catalog、runtime binding 與 SAP execution path。

Runner 介面補上 pilot 的可重現控制：

```text
phase07-experiment prepare-pilot
phase07-experiment make-run-manifests
phase07-experiment integration-check
phase07-experiment record-intervention
```

`prepare-pilot` 以 sealed corpus 計算 Ground Truth／scoring policy hash，並以 researcher-private raw corpus 只生成五份繁體中文任務提示；提示逐份保存 SHA-256，不會把下游文件答案放入提示。它固定 GPT-5.6 Sol、medium reasoning、120 秒與最多 8 次工具呼叫，產生 P01–P05 × A/B/C 的 15-run 交錯 schedule。`make-run-manifests` 將每個 schedule entry 寫成獨立 manifest；每次 run 必須使用全新 Agent session。

研究者可由 `scripts/run_phase07_pilot.py` 的 `prepare → next → serve → finish → status` 依序執行與續跑；環境或決策介入造成無效時使用 `invalidate`，再以 `serve --rerun` 重跑同一 task×condition run ID。腳本將前一次 JSONL 與 raw answer 移入 archive，再建立新的 attempt；每個 slot 最多兩次 rerun，已計分的 run 不可重跑。腳本從本機 `.env` 讀取 HMAC key，不印出 key。`prepare` 會先核對 researcher-private raw corpus 的每筆 SAP 文件物件及 canonical parameters 能重現 approved sealed corpus 的 HMAC，再把文件 ID 投影成 pilot 的離線評分目標；approved sealed corpus 保持固定。這可避免把 whole-object HMAC 與 Agent 的 ID-only 回答直接比較。

最終答案契約固定為 `{"sales_orders":[],"deliveries":[],"billings":[]}`，陣列元素只允許文件 ID 字串。Runner 保存 raw final output 並嚴格解析；無效 JSON、缺欄位或研究者另行提供與 raw output 不一致的 reported outcome 都視為 Agent answer failure，不得人工修補。`record-intervention` 將登入／授權、啟動、環境修復及影響決策的介入寫入不可改寫的 run event；標記 invalid 的 run 不得計分，原始紀錄以 replacement run ID 連回，最多允許兩次 replacement。

正式 15 runs 前必須通過 `integration-check`，確認 frontend、三組 catalog、runtime binding 及每組四個 Site Tools 的靜態定義。由於 Codex SDK／App Server 不保證能綁定 Desktop built-in browser 的指定 tab，研究者可在該整合檢查或正式 run 按一次開始；runner 仍負責 manifest、事件驗證、raw answer 封存與離線評分。

目前腳本可驗證三組 catalog 各有四個工具，實際 Desktop Site Tools 註冊仍須在 built-in browser 逐筆確認。八次呼叫上限於離線評分中判定，超限的 Task Success 為 0；120 秒記於固定 manifest，但手動 Desktop task 啟動尚無可驗證的程式化 timeout enforcement，因此此項必須在正式計分前完成整合驗證。

候選建立使用 `scan-candidates`：它以受治理的 `search_sales_orders` 條件逐筆讀取 10–30 張 Sales Order，對每張資料補做 `get_sales_order`、Delivery/Billing 文件流與 enrichment 查詢，並輸出 ignored `experiment/private/` 下的 `classification: candidate` JSON。輸出只提供排名及 P01–P05 建議配對，不會建立或核准 Ground Truth；D3 只有在非訂單號條件即時重查恰好命中一筆時才算唯一。

原始案例、Agent 原始答案與 review exchange 放在 ignored `experiment/private/`；版本庫只保存 pilot coverage、scoring policy、程式、測試及不含真實 SAP 值的方法文件。

## 公平比較控制

A/B/C 使用相同 tasks、SAP tenant、canonical operations、transport、runtime、logger、scorer 與 scoring policy。唯一主要差異是 Agent-visible tool name、description 與 parameter semantics。Agent 自行決定工具與順序，網站及評分器不得硬編碼 `get_sales_order → delivery → billing`。

## 通過條件

五筆 pilot 均由實際 SAP 資料建立並依 corpus 固定的 review protocol 完成研究者核准；每次 run 均可重建工具選擇、參數、結果與必要頁面狀態；離線 scorer 可在不向 Agent 暴露 Ground Truth 的情況下計算三項指標並區分四類錯誤。完成後才進入 Phase 08，固定 protocol、擴充二十筆 tasks 並執行正式 A/B/C 實驗。
