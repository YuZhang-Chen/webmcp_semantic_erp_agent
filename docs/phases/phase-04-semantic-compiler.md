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

## 原型實作

目前 compiler 入口是 `semantic-model compile`。它會先執行 Phase 03
multi-source strict gate；模型不是 `validated`、evidence 不完整或政策不是
GET-only/no-fallback 時，命令失敗且不產生新的 artifact。

```powershell
uv run python -m semantic_model.cli compile `
  --model semantic_models\sap_sd\model.yaml `
  --evidence semantic_models\sap_sd\evidence\tenant-binding-evidence.json `
  --official-evidence semantic_models\sap_sd\evidence\official-s4hana-2023.json `
  --schema semantic_models\sap_sd\model.schema.json `
  --output build\phase-04\c-semantic-tools.json
```

模型版本已升至 `0.4.0`，所有 Agent-visible input parameter 都有受治理的
業務 description。工具描述以固定順序組合 operation purpose、entity business
description、relationship description 與唯讀政策；工具名稱固定為四個
allowlisted operation ID。

產物是 deterministic C catalog，包含 `schemaVersion`、`condition`、
`compilerVersion`、model id/version/hash/source IDs、四個工具與 `artifactSha256`。
output schema 會攜帶所需的 `$defs`，因此每個 schema 可獨立解析；catalog 不包含
EntitySet、SAP technical property、endpoint、credential 或 raw evidence。

目前 WebMCP draft 的 imperative registration contract 是
`name`、`description`、`inputSchema`、`annotations` 與 `execute`；`outputSchema`
仍未成為 core `ModelContextTool` 欄位。因此 `prototype/webmcp/register-semantic-tools.mjs`
只投影前述 core 欄位，`outputSchema` 僅保留在研究 catalog。這與 OpenAI 官方工具實踐
一致：工具 schema 應透過 tools contract 傳遞，並使用清楚的工具與參數名稱／描述，
再以 eval 或 smoke test 驗證工具使用行為。

最小註冊 smoke test：

```powershell
node scripts\smoke_webmcp_registration.mjs build\phase-04\c-semantic-tools.json
```

## 重要邊界

本階段只產生 C Semantic Tools。A 與 B 不宣稱是 Semantic Compiler 的研究成果，將於 Phase 5 另外定義為 baseline contract。

## 通過條件

C catalog 可被 adapter 投影並註冊四個 WebMCP tools，且每個工具都能追溯回模型中的
operation、parameter 與 policy；同模型重複編譯產生 byte-for-byte 相同檔案與 hash。

Phase 04 不連 SAP、不建立前端工作台，也不引入 OpenAI API key；SAP OData GET
執行與瀏覽器頁面狀態留給 Phase 06。

OpenAI 實踐參考：工具 schema 透過正式 `tools` contract 傳入模型，工具與參數使用清楚
名稱／描述，並以 eval 驗證工具選擇與參數正確性；Responses API 另支援 custom function
與 remote MCP，但不改變本研究的 browser-native WebMCP 邊界。

- [OpenAI Model guidance：tool schemas and descriptions](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-4.1)
- [OpenAI Responses API：tools and MCP tools](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
