# Data dictionary

## Shared fields

| Field | Meaning |
|---|---|
| `run_id` | Coded run identifier; Study 1 uses `F08-...`, Study 2 uses `CB08-...`. |
| `task_id` | Coded task identifier with no SAP document value. |
| `condition` | Tool-description condition: A technical, B typed, or C semantic. |
| `repetition` | Repetition number within a task and condition. |
| `tool_selection_correct`, `tool_decisions` | Correct and scoreable tool decisions. |
| `parameter_correct`, `scored_parameters` | Correct and scoreable task-relevant parameters. |
| `tool_selection_accuracy`, `parameter_accuracy` | Ratios in the range 0–1 in JSON score files. |
| `task_success` | Binary final-task outcome. |
| `error_categories` | Coded scoring categories; free-text errors are omitted. |
| `log_sha256`, `manifest_sha256` | SHA-256 commitments to the corresponding private source artifacts. |

## Study 1

Study 1 contains 20 tasks × 3 conditions × 3 repetitions = 180 analyzed runs. The schedule projection also accounts for 182 recorded attempts: two invalid attempts occurred for one slot, which was ultimately completed by a replacement. Invalid attempts are present in the event projection and lineage but are not included in the 180 scored rows.

`summary.json` contains the scored run rows and aggregate counts. `runs.csv` provides the same run-level score fields in tabular form. Individual score JSON files include run identity, condition, repetition, replacement status, metric counts, metric ratios, error categories, and hashes.

Tool Selection Accuracy is available as both micro and macro in `report.md`: micro aggregates correct decisions over all decisions; macro averages each run's decision ratio. Parameter Accuracy and Task Success definitions and confidence intervals are detailed in the report.

## Study 2

Study 2 contains 12 tasks × 3 conditions × 2 repetitions = 72 runs. Its per-run call budgets are D1=1, D2=2, and D3=3. Exceeding the budget is a valid scored failure; an over-limit call is represented as `executed=false` in the event projection.

`summary.json` includes run-level records, condition and difficulty aggregates, paired comparisons, exact McNemar p-values, Holm-adjusted p-values, and task-cluster bootstrap intervals. The ratios in JSON use the range 0–1; percentages in `report.md` multiply these values by 100.

## Public event projection

`events/all-attempts.jsonl` contains one projected event per line. The projection keeps coded run identity, event sequence and type, tool name, canonical operation, call order, execution and success flags, duration, safe error category, selected runtime configuration, and selected artifact hashes. It omits timestamps, raw arguments, returned SAP values, page-state payloads, raw-answer content or paths, answer hashes, and free-text errors.

`events/index.csv` gives the event count, projected-stream hash, and private source-log hash for each attempt. The hash is not a substitute for access to the private source file.

## Scope

The published records allow readers to recompute aggregate statistics and audit the projected sequence of tool decisions. They do not permit independent rescoring of original Agent answers against the private SAP Ground Truth or replay of the live SAP queries.
