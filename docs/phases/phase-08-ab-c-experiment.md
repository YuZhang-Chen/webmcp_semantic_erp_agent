# Phase 08：Pilot 與正式 A/B/C 實驗

## 目的

驗證語意增強程度是否改善 SAP SD 跨文件查詢中的 Agent 表現。

## Phase 07 交接與啟動 gate

Phase 07 的 P01–P05 × A/B/C、每格一次，共 15 runs，是工具、Ground Truth、trace 與 scorer 的校準；它不是下方的三次重複 Pilot，也不納入正式結果。Phase 08 只能在下列項目經研究者核對後啟動：

1. 五筆 live OData V2 案例按固定 `human_only` protocol 核准；`validate-corpus` 通過，研究者私有 raw 與 approved sealed corpus 的文件物件、canonical parameters 及 ID-only 投影相互驗證。固定 corpus、scoring policy、prompt、模型／版本、catalog、runtime binding 與 transport 的 hash；Ground Truth 不得進入 Agent、網站或 WebMCP catalog。
2. 15 個 task×condition slot 均有可驗證的完成紀錄與離線分數；invalid 原 run 必須保留，replacement 的 lineage、相同 task／condition 與固定 prompt 必須可追溯。以有效 replacement 填補 slot，不將 invalid run 計入分母或當成額外 repetition。
3. 靜態 `integration-check` 通過後，研究者另在 Desktop built-in browser 驗證每組四個 Site Tools 可見並可由全新 Agent task 呼叫；這項人工 gate 不能由 catalog 檔案存在取代。
4. 120 秒上限在手動 Desktop task 啟動模式尚無可驗證的程式化 enforcement。研究員於 2026-09-16 明確豁免受控中斷證據，並承認此限制；因此本次正式結果不得宣稱已驗證 120 秒逾時控制。八次工具呼叫上限仍由離線 scorer 判定，不等於執行期阻擋。

現有 `scripts/run_phase07_pilot.py` 及 `phase07-experiment prepare-pilot` 固定 15-run schedule、`P01`–`P05` 與 `R1`；不能直接用來生成或執行 45／180 runs。Phase 08 應新增獨立的計畫、manifest 與完成驗證流程，不改寫已固定的 Phase 07 artifact。

## Pilot

```text
5 tasks × 3 conditions × 3 repetitions = 45 runs
```

Pilot 不作為正式結果，先檢查任務描述、Ground Truth、prompt、logging 與評分規則是否有系統性問題。

沿用五筆已核准的 live 案例，每筆在 A/B/C 各做三次全新 Agent session。repetition 是預先排程的有效獨立 run，不是 invalid run 的 replacement。每次使用同一任務提示、同一 SAP tenant／transport／頁面狀態、四個 canonical operations、固定 Agent 設定及相同 scorer；交錯並平衡 A/B/C 執行順序，保存排程 seed／演算法及每次 run 的完整身份與 hash。Pilot 分析只用來發現系統性問題；若需調整提示、Ground Truth 或政策，留存版本與理由，重新核准並固定正式實驗的 protocol，不混用修訂前後分數。

## 正式實驗

```text
20 tasks × 3 conditions × 3 repetitions = 180 runs
```

任務分為單一文件、已知訂單跨文件、條件搜尋後跨文件三類，確保涵蓋搜尋、選定訂單與跨文件追蹤。

20 筆 tasks 皆須由明確選定的 live `webmcp.sap_sd.odata` 建立、人工逐項確認並依固定 protocol 核准；先定義 D1/D2/D3 配額、唯一搜尋條件、納入／排除規則與資料時間基線，再固定 task IDs、同一份 corpus revision、task-relevant parameters、三組共用提示及 180-run schedule。不得由 Phase 07 的五題重複湊出二十題，也不得以 fixture、mock、衍生 log 或 model 記憶替代 live 案例。所有 raw evidence、核准 corpus、答案與 log 留在 researcher-private／ignored 路徑；版控只保存無真實 SAP 值的 protocol、程式、測試與彙總結果。

每個 run 使用新的 Agent session，固定順序與重複次數；收集原始最終回答、append-only JSONL、完成檔 SHA-256、分數及 intervention／replacement lineage。沿用 Phase 07 的嚴格 `{"sales_orders":[],"deliveries":[],"billings":[]}` ID-only 答案契約與離線投影核對，不人工修補 Agent 答案。缺事件、身份或 hash 不符、損壞及影響決策的人為介入是程序無效，和 Agent 的工具、參數、SAP 查詢或答案合成錯誤分開報告。不得靜默補事件或以另一 run 的資料回填。

## 主要指標

1. Tool Selection Accuracy：是否選擇適當工具。
2. Parameter Accuracy：工具參數是否正確且符合預期文件。
3. Task Success Rate：是否完成 Ground Truth 所要求的任務。

## 輔助指標

- Tool invocation steps。
- Execution time。
- Invalid or redundant calls。
- 錯誤類型分布。

## 通過條件

每組條件使用相同任務、資料、prompt、執行層與評分規則，結果可重複產生並能追溯模型版本。

先以獨立 Phase 08 runner 測試排程的 45／180 唯一 run ID、每題每組三次、順序平衡、manifest hash 鎖定、invalid/replacement 不重複計數、答案及 log 驗證。正式執行前逐項完成上方 Desktop 與逾時 gate，固定二十題 corpus 和所有控制條件；執行後明列預定、有效、無效、replacement 及缺失 run 數，不把未完成或無效 run 假裝成 Agent 失敗。三項主要指標按 task、condition、repetition 聚合，附帶輔助指標與錯誤分類，保存可重算的分析版本。

## 論文素材

實驗設計表、結果表、錯誤分析與 A/B/C 討論。
