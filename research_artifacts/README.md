# Public research artifacts

This directory contains the de-identified evidence package for two independent WebMCP ERP Agent studies. Study 1 has 180 scored runs; Study 2 has 72 scored runs. The denominators and analyses are kept separate.

## Contents

```text
research_artifacts/
  study1_180_run/                       Study 1 scores, report, schedule and event projections
  study2_constrained_budget_72_run/     Study 2 scores, report, schedule and event projections
  shared_runtime/                       Study protocol, scoring policies, catalogs and bindings
  provenance/                           Source-code provenance and private evidence commitments
  DATA_DICTIONARY.md                    Field definitions and reuse limits
  DATA_LICENSE.md                       CC BY 4.0 terms for this package
  MANIFEST.sha256                       Hashes for every package file except this manifest
```

Each study directory contains one JSON score file per analyzed run, a `summary.json`, a coded `schedule.json`, an `attempt-lineage.json`, and a projected event stream. Study 1 also provides a run-level CSV. The Study 1 event stream includes 182 recorded attempts: 180 analyzed schedule slots, two invalid attempts, and one replacement slot. Study 2 contains 72 scored attempts with no missing or replaced slots.

The event stream omits timestamps, raw parameters, result values, error text, reported outcomes, and raw answer paths. Schedule projections omit task prompt text and prompt hashes. A score's `log_sha256` and `manifest_sha256` refer to the private source artifacts and are included as integrity commitments; the corresponding source payloads are not part of this release.

`provenance/execution-code-provenance.json` records that the experiments ran with two uncommitted runtime changes that were later captured in commit `a5d917229d93043a36c8feb306ddcc97d3814575`. That commit does not represent a byte-for-byte snapshot of each run's working tree.

## Recalculating and checking

The score files and summaries support recalculating the descriptive statistics reported in the papers. The tracked scoring implementation is in `src/experiment/`; the exact policies used by each study are in `shared_runtime/`. The event projection supports checking operation order and run accounting.

This package does not permit independent rescoring of the exact raw Agent answers against Ground Truth. Original Ground Truth, full manifests, original logs, and raw answers remain in researcher-private storage. `provenance/private-evidence-commitments.json` contains only family-level commitments; the private master manifest with per-file hashes remains ignored under `experiment/private/`.

## Rebuild and verify

Run from the repository root:

```powershell
uv run python scripts/build_public_research_release.py
uv run python scripts/build_public_research_release.py --verify-only
```

The builder uses collected local evidence and performs an identifier scan against the available private study evidence. It does not contact SAP. `MANIFEST.sha256` is generated after all package documents and data files have been written.

## License and citation

This package is licensed under CC BY 4.0. See [`DATA_LICENSE.md`](DATA_LICENSE.md). Attribute the study authors and cite the fixed repository release and commit once those URLs and identifiers have been assigned. Do not cite a moving branch as the version used for the results.

## 繁體中文摘要

本目錄保存兩個獨立研究的去識別資料：階段一 180 筆評分、階段二 72 筆評分。套件提供逐次分數、排程、事件投影、評分規則、彙總報告及 SHA-256 清單。原始 Ground Truth、完整 manifest、執行 log 與 Agent 原始回答仍保存在研究者私有目錄，因此公開套件可重算彙總統計與稽核工具順序，但不能重新評分原始回答。
