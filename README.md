# WebMCP Semantic ERP Agent

A research prototype for comparing technical, typed, and semantic WebMCP tool descriptions in read-only SAP SD cross-document tasks.

## Research studies

The public release reports two separate studies. Study 1 contains 180 scored runs across 20 tasks, three conditions, and three repetitions. Study 2 is an independent constrained-budget supplement containing 72 scored runs across 12 tasks, three conditions, and two repetitions. Their sample sizes, denominators, and statistical tests are reported separately.

The de-identified score records, coded schedules, event projections, runtime catalogs, scoring policies, reports, and SHA-256 manifest are under [`research_artifacts/`](research_artifacts/README.md). These data let readers check run-level scores, recalculate aggregate statistics, and inspect projected tool-call sequences. The public release cannot independently rescore original answers because SAP Ground Truth values and raw answers remain private.

## Evidence and limits

The experiments used two runtime changes that were uncommitted while the runs were performed. Those changes were later recorded in commit `a5d917229d93043a36c8feb306ddcc97d3814575`; this post-hoc commit documents the changes but does not establish a byte-for-byte snapshot of every run's working tree.

Study 1 used an eight-call limit. Controlled 120-second timeout-interruption evidence was waived by the researcher, so this repository does not claim that runtime timeout enforcement was validated. The original Ground Truth, exact task prompts, raw Agent answers, and full execution logs may contain SAP identifiers and are not included. A private evidence manifest is generated locally at `experiment/private/release-v1.0.0-private-evidence-manifest.json`; it must remain in encrypted researcher storage.

Phase 07 pilot records are not part of the two reported studies. The repository retains their development history, while the public research package contains only Study 1 and Study 2 evidence.

## Build and verify the research package

From this repository root:

```powershell
uv run python scripts/build_public_research_release.py
uv run python scripts/build_public_research_release.py --verify-only
```

The builder reads already-collected local files and does not contact SAP. A release copy can be checked with the second command without private evidence files. `research_artifacts/MANIFEST.sha256` covers every file in the public research package except the manifest itself.

## Licensing

- Source code: MIT License, in [`LICENSE`](LICENSE).
- Research protocols, documentation, reports, and de-identified research artifacts: Creative Commons Attribution 4.0 International (CC BY 4.0), as described in [`research_artifacts/DATA_LICENSE.md`](research_artifacts/DATA_LICENSE.md).
- SAP source records, private Ground Truth, raw answers, credentials, and tenant configuration are not included and are not licensed by this repository.

The MIT license text is published by the [Open Source Initiative](https://opensource.org/license/mit). The official [CC BY 4.0 deed](https://creativecommons.org/licenses/by/4.0/) and [legal code](https://creativecommons.org/licenses/by/4.0/legalcode) describe the data and documentation license.

## 中文摘要

本專案比較技術、型別與語意三種 WebMCP 工具描述在 SAP SD 唯讀跨文件任務中的表現。公開研究包將階段一 180 runs 與階段二 72 runs 分開保存，提供去識別逐次評分、排程、事件投影、統計摘要與完整性雜湊。SAP Ground Truth、實際任務提示、原始 Agent 回答及完整執行紀錄不公開；公開資料可重算彙總統計並稽核事件順序，但無法獨立對私有 Ground Truth 重新評分。

論文第四章與第六章附錄的放置建議見 [`docs/paper-publication-guide.md`](docs/paper-publication-guide.md)。GitHub repository、release 與最終 commit 連結將於 repository 建立後補入論文附錄。
