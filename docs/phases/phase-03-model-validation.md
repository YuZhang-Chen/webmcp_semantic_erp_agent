# Phase 3：Semantic Model 與 Validation

## 目的

把 Phase 2 的設計轉成可驗證的機器可讀模型，讓錯誤在建置期被發現。

## 本階段工作

1. 建立模型版本與 model identifier。
2. 驗證 entity、relationship 與 operation 的引用完整性。
3. 驗證參數名稱、型別、格式、長度與必填規則。
4. 驗證所有 operation 都是 GET 且具 read-only policy。
5. 驗證每個 operation 都有 OData binding 與 output schema。
6. 以錯誤模型執行負向測試。

## 階段產出

- 可載入的最小 Semantic Model。
- Validation 規則清單。
- 正向與負向驗證案例。

## 通過條件

無效模型不能進入編譯階段；有效模型可穩定載入且具有版本資訊。

## 論文素材

Semantic Governance Model 的欄位分類、驗證流程與建置期治理價值。
