# Phase 07 experiment artifacts

Tracked files define the five-task pilot coverage and the scoring policy. Actual SAP case values, raw Agent answers, review exchanges, Ground Truth drafts and execution logs belong under `experiment/private/` or ignored `build/phase-07/` paths.

The lifecycle is:

1. Author a private Ground Truth draft from live `webmcp.sap_sd.odata` results.
2. After researcher verification, run `confirm-ground-truth`, then `phase07-experiment seal-corpus`.
3. For `human_only`, run `approve-ground-truth` directly. For `human_plus_llm`, export a de-identified review packet, import the structured response, and resolve disagreements by checking SAP again.
4. Run `validate-corpus` before any experiment run.
5. Freeze the pilot protocol with `prepare-pilot`, materialize its 15 manifests with `make-run-manifests`, and pass `integration-check` before starting runs.
6. Start the shared workbench with `python scripts/serve_phase07.py --run-manifest <private-manifest>`.
7. Save the raw Agent answer exactly as returned, then run `close-run --answer-file <raw-answer>`. The runner parses the fixed JSON contract; do not hand-edit a reported outcome.
8. Run `score-run` for valid runs. Use `record-intervention --invalid --replacement-run-id <new-id>` for infrastructure or decision-affecting human intervention.

`HMAC_KEY` must remain local and stable for one corpus (`PHASE07_HMAC_KEY` remains a compatibility alias for the server). Ground Truth is never served through `/runtime/*` or registered as a WebMCP tool.

## Phase 08 pilot and formal experiment

Phase 08 has a separate CLI and never rewrites the Phase 07 plan or manifests. It
freezes a deterministic 45-run pilot or 180-run formal schedule, validates the
approved `human_only` corpus, and writes one manifest per scheduled slot:

```powershell
$env:UV_CACHE_DIR = '.uv-cache-phase08'
uv run phase08-experiment prepare --mode pilot `
  --ground-truth experiment/private/ground-truth-sealed.json `
  --raw-ground-truth experiment/private/ground-truth-raw.json `
  --policy experiment/scoring-policy.json `
  --output experiment/private/phase08-pilot-plan.json
uv run phase08-experiment make-run-manifests `
  --plan experiment/private/phase08-pilot-plan.json `
  --output-dir experiment/private/phase08-run-manifests
```

The independent constrained-budget supplement uses `phase08-budget-experiment`
for corpus derivation, plan/manifests, headless execution, scoring and summary.
It adds 72 runs without changing the v1 180-run denominator. Budget exhaustion
is a valid scored failure; only infrastructure failures may be replaced. See
`docs/phases/phase-08-constrained-budget-study.md` for the freeze attestation
and complete command sequence.

Use `--mode formal` only with a separately approved twenty-case live corpus
whose difficulty quota is D1/D2/D3 = 4/8/8. Before either schedule starts,
run `verify-phase07-gate`, perform the Desktop Site Tools check, and provide
the controlled 120-second interruption evidence to `integration-check`.
For gradual 2026 formal case discovery, scan exactly one month per invocation:

```powershell
uv run phase08-experiment scan-month --month 2026-01
uv run phase08-experiment candidate-status
```

`scan-month` reads up to 30 initial Sales Orders via the pinned OData V2 GET
binding, then confirms each candidate through the governed operations. It
creates a new `experiment/private/phase08/YYYY-MM-candidates.json` and refuses
to overwrite an existing month. The status command prints only counts,
month-level completeness indicators and hashes. Zero-record months remain
recorded as valid discovery attempts. Run later months separately, stop when
the live candidate pool supports 20 distinct approved cases and the fixed
quota, and have the researcher reconfirm each case before sealing the formal
corpus. A scan reaching the 30-order cap requires a separate pagination or
criteria review before claiming the month is complete.
`phase08-experiment serve --run-manifest <manifest>` uses the shared workbench;
`close-run`, `verify-log`, and `record-intervention` retain the Phase 07 append-only
event and raw-answer rules. After runs, `summarize` reports planned, valid,
invalid, replacement and missing slots, with aggregates by condition, task and
repetition.

The headless prototype keeps the same catalog and runtime binding while
replacing the browser handoff with a provider-neutral tool-calling loop. Check
the prerequisites without loading Ground Truth, then run one manifest through
the local gateway (or an explicit private replay):

```powershell
uv run phase08-experiment headless-check `
  --catalog-dir build/phase-05 `
  --bindings build/phase-06/runtime-bindings.json
uv run phase08-experiment headless-run `
  --run-manifest experiment/private/phase08/formal-run-manifests-six-priority-v1/F08-T01-A-R1.json `
  --config http://localhost:5173/runtime/config.json `
  --bindings build/phase-06/runtime-bindings.json `
  --output experiment/private/phase08/answers/F08-T01-A-R1.txt
```

For a complete schedule, `headless-batch` requires the frozen plan and executes
manifests in its `schedule` order rather than filename order. It rejects missing,
unexpected, or plan-mismatched manifests. Each successful headless run archives
the exact raw answer beside its log and records the same parsed, pseudonymized
`reported_outcome` contract used by the Phase 07 scorer:

```powershell
uv run phase08-experiment headless-batch `
  --plan experiment/private/phase08/formal-plan-six-priority-v1.json `
  --manifest-dir experiment/private/phase08/formal-run-manifests-six-priority-v1 `
  --config http://localhost:5173/runtime/config.json `
  --output-dir experiment/private/phase08/answers `
  --log-dir build/phase-08/headless-runs
```

Headless runs are already closed by the runner. Do not invoke `close-run` on
their logs; proceed directly to `verify-log` and `phase07-experiment score-run`.

Azure mode requires `AI_PROVIDER=azure_openai`, `AZURE_OPENAI_API_KEY`,
`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`,
`HEADLESS_AGENT_MODEL=gpt-5.6-sol` and `HMAC_KEY`.
The Azure endpoint is the resource root; the runner appends
`/openai/v1/responses`. Responses API v1 does not require `api-version`.
It creates an append-only headless log and never falls back from live mode to
replay. Replay is engineering-only and must be passed explicitly with
`--replay`.

For the Desktop pilot, one script coordinates the researcher-side sequence from the repository root:

```powershell
$env:UV_CACHE_DIR = '.uv-cache-phase07'
uv run python scripts/run_phase07_pilot.py prepare
uv run python scripts/run_phase07_pilot.py next
uv run python scripts/run_phase07_pilot.py serve --run-id P01-A-R1
```

Keep `serve` running while opening the printed workbench URL in ChatGPT Desktop built-in browser. Verify that the page registers four Site Tools. Create a fresh Codex task, use the printed fixed Agent instruction and task prompt, and save the raw final answer exactly as returned. Stop `serve`, then finish in another PowerShell command:

```powershell
uv run python scripts/run_phase07_pilot.py finish --run-id P01-A-R1 --answer-file experiment/private/answers/P01-A-R1.txt
uv run python scripts/run_phase07_pilot.py next
uv run python scripts/run_phase07_pilot.py status
```

If the run failed because of infrastructure or decision-affecting human intervention, stop `serve` and use `invalidate` to record the reason. Then start the same task×condition run ID with `--rerun`; the previous JSONL and raw answer are moved to `build/phase-07/runs/archive/` and the new attempt keeps the same fixed prompt and condition:

```powershell
uv run python scripts/run_phase07_pilot.py invalidate --run-id P01-A-R1 --type environment_repair --operator researcher-01 --note 'SAP gateway HTTP 502'
uv run python scripts/run_phase07_pilot.py serve --run-id P01-A-R1 --rerun
```

This preserves the original log and starts a new attempt under the same run ID. A scored run cannot be rerun, and each slot permits at most two reruns. The script checks the approved sealed corpus against the researcher-private raw counterpart before projecting the document IDs for ID-only scoring. The approved sealed corpus itself remains unchanged. The browser-side Codex task is started by the researcher because the local CLI has not been verified to attach to a Desktop built-in browser tab. The 8-call threshold is checked in offline scoring; the 120-second limit is fixed in the plan but cannot be enforced by this manual Desktop handoff yet.
