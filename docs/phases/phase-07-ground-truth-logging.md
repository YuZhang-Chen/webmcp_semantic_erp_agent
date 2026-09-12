# Phase 7：Ground Truth 與 Agent Execution Logging

## 目的

建立獨立且可追溯的評估基礎，使 Agent 的選擇行為能被分析，而不是只展示最後答案。

## 本階段工作

1. 設計五個 pilot tasks，再擴充至二十個正式 tasks。
2. 由人工確認每個訂單、交貨與請款關聯，建立 Ground Truth。
3. Ground Truth 與 Agent 執行程序分離。
4. 記錄工具名稱、參數、呼叫順序、錯誤類型與結果摘要。
5. 預設不保存原始 SAP rows，只保存列數、摘要與內容雜湊。
6. 區分工具選擇錯誤、參數錯誤、SAP 查詢錯誤與答案整理錯誤。
7. 記錄每次呼叫前後的頁面狀態摘要，例如目前選取訂單、結果清單筆數及文件流程節點。

## Agent 流程原則

實驗不得把 `get_sales_order → delivery → billing` 寫死。該流程只能作為 execution trace 範例；正式執行時由 Agent 自行決定工具與順序。

## 通過條件

每一筆 run 都能重建 Agent 的工具決策、工具造成的頁面狀態轉換及其評分依據，且評分器不會把 Ground Truth 暴露給 Agent。

## 論文素材

任務格式、Ground Truth 建立方式、logging schema 與錯誤分類表。
