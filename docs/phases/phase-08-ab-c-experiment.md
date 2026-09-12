# Phase 8：Pilot 與正式 A/B/C 實驗

## 目的

驗證語意增強程度是否改善 SAP SD 跨文件查詢中的 Agent 表現。

## Pilot

```text
5 tasks × 3 conditions × 3 repetitions = 45 runs
```

Pilot 不作為正式結果，先檢查任務描述、Ground Truth、prompt、logging 與評分規則是否有系統性問題。

## 正式實驗

```text
20 tasks × 3 conditions × 3 repetitions = 180 runs
```

任務分為單一文件、已知訂單跨文件、條件搜尋後跨文件三類，確保涵蓋搜尋、選定訂單與跨文件追蹤。

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

## 論文素材

實驗設計表、結果表、錯誤分析與 A/B/C 討論。
