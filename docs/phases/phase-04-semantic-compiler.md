# Phase 4：Semantic Compiler 與 C 組工具

## 目的

將已驗證的 Semantic Model 以確定性規則編譯成 WebMCP Tool Schema，形成 C Semantic condition 的正式產物。

## 編譯流程

```text
Semantic Model
      ↓
Validation
      ↓
Deterministic Semantic Compiler
      ↓
name / description / inputSchema / annotations / outputSchema
      ↓
WebMCP Tool Definition
```

## 本階段工作

1. 產生企業語意工具名稱與描述。
2. 將業務參數映射成 WebMCP `inputSchema`。
3. 將關係與操作目的加入工具描述。
4. 將唯讀政策映射成工具註記。
5. 產生 model hash、compiler version 與 artifact hash。
6. 驗證相同模型重複編譯會得到相同結果。

## 重要邊界

本階段只產生 C Semantic Tools。A 與 B 不宣稱是 Semantic Compiler 的研究成果，將於 Phase 5 另外定義為 baseline contract。

## 通過條件

C 工具定義可被 WebMCP 註冊，且每個工具都能追溯回模型中的 operation、parameter 與 policy。
