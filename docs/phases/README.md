# 研究導向實作階段

本目錄將「WebMCP 之 ERP 跨文件查詢代理：以 SAP SD 訂單流程為例」拆成可逐步吸收的十個階段。每個階段都遵循：理解概念、檢查證據、完成最小產出、測試或核對、整理論文素材、經確認後再進入下一階段。

## 研究主線

```text
研究目的與控制變因
        ↓
Browser → SAP OData 連線閘門
        ↓
Semantic Analytics（設計參考）
        ↓
SAP SD 最小語意模型
        ↓
Model Validation
        ↓
Semantic Compiler → C Semantic Tools
        ↓
A Technical / B Typed / C Semantic
        ↓
WebMCP + Shared Application Actions + SAP OData V2
        ↓
Ground Truth + Agent Logging
        ↓
Pilot 與正式 A/B/C 實驗
        ↓
六頁研討會論文
```

## 固定研究範圍

- 研究情境：SAP SD 銷售訂單、外向交貨、請款文件的跨文件查詢。
- 研究工具：`search_sales_orders`、`get_sales_order`、`get_related_deliveries`、`get_related_billing_documents`。
- 執行權限：SAP 唯讀、只發出 HTTP GET。
- 主要協定：已確認可用的 SAP OData V2。
- Agent 入口：使用者在 ChatGPT／Codex 對話區下達自然語言任務；網站本身不內嵌 LLM 或 Agent Controller。
- 網頁角色：網站註冊 WebMCP tools，並與 Agent 共用目前開啟頁面的搜尋條件、選取訂單與文件流程狀態。
- 執行架構：不設置自建應用後端；瀏覽器端共用操作直接以 HTTPS GET 呼叫 SAP OData，SAP ERP 為系統後端。
- 原型驗證：帳號密碼由本機 `.env` 提供；SAP 受信任憑證位於 Windows 憑證存放區。此作法只限隔離的教學原型。
- 停止條件：若目標瀏覽器的 CORS、TLS、驗證或 OData 連線測試失敗，停止實作並由研究者共同處理，不自行加入代理層或 fallback。
- OData V4：工程上的 optional extension，不列為研討會主要研究階段。
- 主要實驗：20 tasks × 3 conditions × 3 repetitions = 180 runs。
- Pilot：5 tasks × 3 conditions × 3 repetitions = 45 runs。
- 主要指標：Tool Selection Accuracy、Parameter Accuracy、Task Success Rate。

## Git 版控限制

- `docs/` 與其下的 `docs/phases/` 僅供本機研究規劃；本機 AI Agent 必須能讀取及使用，但不納入 Git 版控，因此不會出現在 remote repository。
- 根目錄 `AGENTS.md` 同樣只供本機 Agent 使用，必須可讀但不得納入 Git 或發布到 remote repository。
- `.gitignore` 只限制 Git 追蹤，不限制本機 Agent 存取；Agent 不得因該目錄被忽略而刪除、搬移或略過其中的規劃。
- 必須先由根目錄 `.gitignore` 忽略 `docs/` 與 `.env`，並驗證規則生效後，才能初始化 Git、加入檔案或建立提交。
- 不得以 force add 將 `docs/` 納入追蹤；若日後需要調整，必須先取得研究者明確同意。

## A/B/C 控制原則

三組共用相同的 canonical execution layer、SAP binding、輸出與評分方式，只有 Agent 可看到的工具介面語意程度不同。

三組也共用同一個網站畫面與頁面狀態；不能用不同 UI 或不同前端流程來影響 Agent 的選擇結果。

- A Technical：OData 實體集與技術欄位導向的 baseline。
- B Typed：型別、參數結構與一般功能描述的 baseline。
- C Semantic：由 Semantic Model 驗證及編譯產生，含企業概念、文件關係、操作目的與唯讀政策。

## 階段索引

| 文件 | 階段 |
| --- | --- |
| [phase-00-research-scope.md](phase-00-research-scope.md) | 研究目的與控制變因 |
| [phase-01-semantic-analytics-reference.md](phase-01-semantic-analytics-reference.md) | Browser–SAP 連線閘門與最小治理欄位 |
| [phase-02-sap-sd-semantic-model.md](phase-02-sap-sd-semantic-model.md) | SAP SD 語意模型設計 |
| [phase-03-model-validation.md](phase-03-model-validation.md) | Semantic Model 與 Validation |
| [phase-04-semantic-compiler.md](phase-04-semantic-compiler.md) | Semantic Compiler 與 C 工具 |
| [phase-05-baseline-conditions.md](phase-05-baseline-conditions.md) | A/B baseline 與 C semantic tools |
| [phase-06-webmcp-odata-v2.md](phase-06-webmcp-odata-v2.md) | WebMCP 直接串接 SAP OData V2 |
| [phase-07-ground-truth-logging.md](phase-07-ground-truth-logging.md) | Ground Truth 與 Agent logging |
| [phase-08-ab-c-experiment.md](phase-08-ab-c-experiment.md) | Pilot 與正式 A/B/C 實驗 |
| [phase-09-paper-integration.md](phase-09-paper-integration.md) | 論文整合 |
