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
