# Phase 8 constrained-budget study

Study 2 is an independent supplementary experiment. It keeps the original
Phase 8 v1 180-run result unchanged and adds 12 approved cases × 3 conditions
× 2 repetitions = 72 runs. The only manipulation is the per-task tool-call
budget: D1=1, D2=2, D3=3. Optional operations are empty for every difficulty.

The corpus is derived from the approved raw/sealed v1 pair. Candidate files
from Claude, Gemini and ChatGPT are provenance only; they never become agent
evidence or Ground Truth. Before freeze, a researcher must reconfirm the 12
live SAP cases and write an attestation with `source_id`, `researcher`,
`confirmed_at`, `status: confirmed`, and the exact selected source task IDs.
Copy `experiment/private/phase08/budget-freshness-attestation.example.json`
to `budget-freshness-attestation.json`, replace the placeholders only after
the live confirmation, and change `status` to `confirmed`. Do not use the
example file directly; the CLI intentionally rejects `pending_manual_confirmation`.

## Reproducible lifecycle

Run from `webmcp_semantic_erp_agent`:

```powershell
uv run phase08-budget-experiment derive-corpus --raw-parent experiment/private/phase08/formal-ground-truth-raw-human-confirmed-v1.json --sealed-parent experiment/private/phase08/formal-ground-truth-sealed-approved-v1.json --candidate-dir experiment/private/candidate --freshness-attestation experiment/private/phase08/budget-freshness-attestation.json --raw-output experiment/private/phase08/budget-ground-truth-raw-v1.json --sealed-output experiment/private/phase08/budget-ground-truth-sealed-v1.json
uv run phase08-budget-experiment prepare --raw-ground-truth experiment/private/phase08/budget-ground-truth-raw-v1.json --sealed-ground-truth experiment/private/phase08/budget-ground-truth-sealed-v1.json --policy experiment/phase08-budget-scoring-policy.json --output experiment/private/phase08/budget-plan-v1.json
uv run phase08-budget-experiment make-run-manifests --plan experiment/private/phase08/budget-plan-v1.json --output-dir build/phase-08-budget/manifests
uv run phase08-budget-experiment integration-check --plan experiment/private/phase08/budget-plan-v1.json --manifest-dir build/phase-08-budget/manifests
```

After the integration check, start the existing local gateway and run the
headless batch with the fixed `gpt-5.6-sol` model, then score and summarize:

```powershell
uv run phase08-budget-experiment headless-batch --plan experiment/private/phase08/budget-plan-v1.json --manifest-dir build/phase-08-budget/manifests --config <runtime-config.json> --output-dir build/phase-08-budget/answers --log-dir build/phase-08-budget/logs
uv run phase08-budget-experiment score-batch --plan experiment/private/phase08/budget-plan-v1.json --manifest-dir build/phase-08-budget/manifests --log-dir build/phase-08-budget/logs --raw-ground-truth experiment/private/phase08/budget-ground-truth-raw-v1.json --sealed-ground-truth experiment/private/phase08/budget-ground-truth-sealed-v1.json --policy experiment/phase08-budget-scoring-policy.json --score-dir build/phase-08-budget/scores
uv run phase08-budget-experiment summarize --plan experiment/private/phase08/budget-plan-v1.json --score-dir build/phase-08-budget/scores --output build/phase-08-budget/summary.json
```

An attempted call at `limit + 1` is logged as `executed=false`, the run ends
with `termination_reason=tool_call_limit_exceeded`, and remains a valid scored
failure. Only provider, SAP, or other infrastructure failures are invalid and
eligible for a lineage-preserving replacement. Study 1 and Study 2 are never
merged in denominators or significance tests.
