# Phase 5：A/B Baseline 與 C Semantic Tools

## 目的

建立可公平比較的三種工具介面，並把自變因限制為 Agent 所看到的語意增強程度。

## 三組條件

### A Technical Baseline

以 OData entity set、技術工具名稱與 SAP 技術欄位描述為主。

### B Typed Baseline

加入一般功能描述、業務化參數名稱、型別、必填與格式限制，但不加入文件關係與完整商業語意。

### C Semantic Tools

使用 Phase 4 的 Semantic Compiler 產物，包含企業概念、文件關係、操作目的、參數業務意義與唯讀政策。

## 控制變因

三組必須共用：

- 相同四個 canonical operations。
- 相同 SAP OData binding。
- 相同輸入資料與輸出結構。
- 相同 browser-side canonical execution layer。
- 相同網站畫面、頁面狀態與操作權限。
- 相同 prompt、任務與評分方式。

## 通過條件

三組只有工具名稱、描述、參數語意暴露程度不同；不能因某組使用不同查詢邏輯、不同網站畫面或不同前端狀態而產生混淆變因。

## 論文素材

A/B/C 工具契約比較表與控制變因說明。
