# Study 1 正式 A/B/C 實驗報告

- 匯出時間（UTC）：`2026-09-16T12:32:06.236291+00:00`
- Protocol：`phase08-ab-c-experiment` / `phase08-1.0`
- 資料來源：`webmcp.sap_sd.odata`（live SAP OData V2，唯讀）
- 排程 seed：`20260915`
- Schedule SHA-256：`29eb4d3755ff28411810e56139397dec5f6f7964dcc2fc968aa1e8ba828c8828`
- Ground Truth SHA-256：`ba2e20e24564816b22e7204cd7d6ac9972e3b1ae654dfc4badefe619a1dbef8b`
- Scoring policy SHA-256：`9654116508bc92c4a337a3b989464d494eb404bae378b7a6fec9f77f4d934615`

## 執行完整性

- 預定 runs：180；有效 runs：180。
- 缺失 runs：0；正式 slot replacements：1。
- 原始無效嘗試保留數：2；不納入正式分母。
- 正式設計：20 tasks × 3 conditions × 3 repetitions = 180 runs。
- 難度配額：D1/D2/D3 = 4/8/8。
- Agent：`gpt-5.6-sol`，reasoning `medium`，每個 run 使用全新 session。
- 工具呼叫上限：8。
- 120 秒 timeout gate：研究者已明確豁免；本結果不得宣稱已驗證執行期 timeout enforcement。

## 指標定義：macro 與 micro Tool Selection

- **Micro Tool Selection Accuracy**：先加總所有 run 的正確 tool decisions 與全部被評分 decisions，再計算 `Σcorrect / Σdecisions`；tool calls 較多的 run 權重較大。原始報告中的 Tool Selection Accuracy 即此定義。
- **Macro Tool Selection Accuracy**：先計算每個 run 的 `correct / decisions`，再對 60 個 runs 取算術平均；每個 `task × repetition` run 權重相同。
- 缺少 required operation 不直接增加 Tool Selection 分母，而由 Task Success 處罰；因此 Tool Selection 較接近 decision precision，而非完整性指標。
- Tool micro/macro 的 95% CI 使用以 task 為 cluster 的 percentile bootstrap（20,000 次、固定 protocol seed），同一 task 的三次 repetitions 一起重抽。Parameter micro 與 Task Success 的條件內 CI 使用 Wilson score interval，以避免全成功條件產生退化的 `[100%, 100%]` bootstrap interval。

## 整體結果

| 範圍 | Runs | Tool micro | Tool macro | Parameter micro | Task Success |
| --- | ---: | ---: | ---: | ---: | ---: |
| Overall | 180 | 85.63% | 86.67% | 99.67% | 98.89% |

## 各條件結果與 95% CI

| Condition | Runs | Tool micro [95% CI] | Tool macro [95% CI] | Parameter micro [95% CI] | Task Success [95% CI] |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 60 | 85.37% [71.76%, 96.36%] | 86.67% [73.33%, 96.67%] | 99.02% [96.50%, 99.73%] | 96.67% [88.64%, 99.08%] |
| B | 60 | 85.28% [71.60%, 96.34%] | 86.67% [73.33%, 96.67%] | 100.00% [98.15%, 100.00%] | 100.00% [93.98%, 100.00%] |
| C | 60 | 86.21% [72.73%, 96.57%] | 86.67% [73.33%, 96.67%] | 100.00% [98.15%, 100.00%] | 100.00% [93.98%, 100.00%] |

### 相對於 A 的差異（百分點）

| 比較 | Tool micro | Parameter micro | Task Success |
| --- | ---: | ---: | ---: |
| B − A | -0.09 | +0.98 | +3.33 |
| C − A | +0.84 | +0.98 | +3.33 |

## 配對檢定

配對鍵為相同的 `task_id × repetition`。Tool macro 與 Parameter macro 先在每個 task 內平均三次 repetitions，再做雙尾 exact sign-flip permutation test；Task Success 使用 60 對 binary outcomes 的雙尾 exact McNemar test。差異的 95% CI 為 task-cluster paired bootstrap；p 值同時提供各 metric 三組比較的 Holm 校正。

| 比較 | Metric | 差異 pp [95% CI] | Discordant pairs | Raw p | Holm p |
| --- | --- | ---: | ---: | ---: | ---: |
| B − A | Tool macro | +0.00 [+0.00, +0.00] | — | 1.0000 | 1.0000 |
| B − A | Parameter macro | +3.33 [+0.00, +8.33] | — | 0.5000 | 1.0000 |
| B − A | Task Success | +3.33 [+0.00, +8.33] | 0 / 2 | 0.5000 | 1.0000 |
| C − A | Tool macro | +0.00 [+0.00, +0.00] | — | 1.0000 | 1.0000 |
| C − A | Parameter macro | +3.33 [+0.00, +8.33] | — | 0.5000 | 1.0000 |
| C − A | Task Success | +3.33 [+0.00, +8.33] | 0 / 2 | 0.5000 | 1.0000 |
| C − B | Tool macro | +0.00 [+0.00, +0.00] | — | 1.0000 | 1.0000 |
| C − B | Parameter macro | +0.00 [+0.00, +0.00] | — | 1.0000 | 1.0000 |
| C − B | Task Success | +0.00 [+0.00, +0.00] | 0 / 0 | 1.0000 | 1.0000 |

Discordant pairs 以「前者成功/後者失敗」與「前者失敗/後者成功」表示。所有檢定均為雙尾；`α = 0.05`。

## 各 repetition 結果

| Repetition | Runs | Tool micro | Parameter micro | Task Success Rate |
| --- | ---: | ---: | ---: | ---: |
| 1 | 60 | 85.63% | 99.51% | 98.33% |
| 2 | 60 | 85.63% | 99.51% | 98.33% |
| 3 | 60 | 85.63% | 100.00% | 100.00% |

## 各 task 結果

| Task | Runs | Tool micro | Parameter micro | Task Success Rate |
| --- | ---: | ---: | ---: | ---: |
| F08-T01 | 9 | 33.33% | 100.00% | 100.00% |
| F08-T02 | 9 | 33.33% | 88.89% | 88.89% |
| F08-T03 | 9 | 33.33% | 100.00% | 100.00% |
| F08-T04 | 9 | 33.33% | 88.89% | 88.89% |
| F08-T05 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T06 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T07 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T08 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T09 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T10 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T11 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T12 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T13 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T14 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T15 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T16 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T17 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T18 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T19 | 9 | 100.00% | 100.00% | 100.00% |
| F08-T20 | 9 | 100.00% | 100.00% | 100.00% |

## 錯誤分類

| Error category | Count |
| --- | ---: |
| `parameter_error` | 2 |
| `tool_selection_error` | 36 |

## 無效嘗試與 replacement lineage

| Invalid attempt | 原因 |
| --- | --- |
| `F08-T10-A-R1-X1` | Headless observer failed because Mapping was not imported; implementation corrected and regression-tested. |
| `F08-T10-A-R1` | Headless gateway omitted sap-client and sap-language, causing SAP HTTP 401; implementation corrected and regression-tested. |

有效 replacement：`F08-T10-A-R1-X2`，填補 frozen schedule 的 `F08-T10-A-R1` slot。

## 解讀與限制

- B 與 C 的 Parameter Accuracy 與 Task Success Rate 均為 100%；A 有兩個 task failure。
- Tool micro 因不同 run 的 decision 數不同而呈現小幅條件差異；Tool macro 三組皆為 86.67%，配對差異為 0。
- B/C 相對 A 的 Parameter macro 與 Task Success 點估計較高，但 exact paired tests 在 Holm 校正後均未達 `α = 0.05`。
- 信賴區間與檢定以 task 為推論 cluster；只有 20 個 task，統計檢定力有限，不應把未顯著解讀為條件等效。
- Ground Truth、raw answers 與 SAP business identifiers 保留於 researcher-private／ignored artifacts，不納入本報告。
- timeout enforcement 未經驗證，八次工具呼叫上限由 runner/scorer 控制與判定。

## Public release artifacts

- Run-level CSV: `runs.csv`
- Canonical run-level summary: `summary.json`
- Individual scores: `scores/*.json`
- Coded schedule and attempt lineage: `schedule.json`, `attempt-lineage.json`
- Event projections: `events/all-attempts.jsonl` and `events/index.csv`

The original manifests, execution logs, Ground Truth and raw answers remain private.
