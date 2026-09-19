# 實作與方法紀錄

本目錄保留 Phase 03–08 的模型驗證、工具條件、執行架構、評分方法與實驗流程紀錄。文件中的版本號與階段狀態只代表當時紀錄；遇到與現況不同之處時，以現行模型契約與固定研究資料為準：

1. [`semantic_models/sap_sd/model.yaml`](../../semantic_models/sap_sd/model.yaml)：現行語意模型、操作、binding 與 runtime policy。
2. [`research_artifacts/`](../../research_artifacts/README.md)：Study 1 與 Study 2 的公開 protocol、去識別評分、事件投影與報告。
3. [`README.md`](../../README.md)：研究包範圍、資料限制與發布說明。

## 研究主線

```text
Multi-source model validation
        ↓
Deterministic compiler and A/B/C tool catalogs
        ↓
Browser WebMCP + shared SAP OData V2 runtime
        ↓
Ground Truth, execution trace and offline scoring
        ↓
Study 1: 180 scored runs
        ↓
Study 2: 72 constrained-budget scored runs
```

Study 1 與 Study 2 使用獨立排程、有效樣本數及統計分析。Phase 07 pilot 與開發用紀錄不納入兩項研究的正式結果。

## 階段索引

| 文件 | 內容 |
| --- | --- |
| [phase-03-model-validation.md](phase-03-model-validation.md) | SAP 多來源證據、模型驗證與 binding 狀態 |
| [phase-04-semantic-compiler.md](phase-04-semantic-compiler.md) | Semantic Compiler 與 C 組工具 |
| [phase-05-baseline-conditions.md](phase-05-baseline-conditions.md) | A/B/C 條件定義與公平比較控制 |
| [phase-06-webmcp-odata-v2.md](phase-06-webmcp-odata-v2.md) | WebMCP 工作台與 SAP OData V2 runtime |
| [phase-07-ground-truth-logging.md](phase-07-ground-truth-logging.md) | Ground Truth、執行紀錄與離線評分方法 |
| [phase-08-ab-c-experiment.md](phase-08-ab-c-experiment.md) | 主要 180-run 研究方法 |
| [phase-08-constrained-budget-study.md](phase-08-constrained-budget-study.md) | 72-run 受限額度補充研究方法 |

## 本機圖檔與版控

`docs/diagrams/` 保留本機可編輯與渲染圖檔，依專案版控規則不追蹤、不發布。忽略規則不代表可刪除該目錄或其中內容。
