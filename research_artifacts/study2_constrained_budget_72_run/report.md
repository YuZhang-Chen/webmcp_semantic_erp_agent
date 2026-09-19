# Study 2 constrained-budget experiment report

Study 2 is an independent supplementary study. It contains 12 coded tasks, three tool-description conditions, two repetitions per condition, and 72 valid runs. The per-task call budget equals the minimum required operations: D1=1, D2=2, and D3=3. Its denominator and tests are separate from Study 1.

Execution accounting: 72 of 72 planned runs scored; 0 invalid slots, 0 replacement slots, and 0 missing scores.

## Results by condition

| Condition | Runs | Success under budget | First choice | Minimal tool set | Budget exhaustion | Excess calls | Parameter accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 24 | 62.50% | 95.83% | 62.50% | 33.33% | 15.28% | 83.33% |
| B | 24 | 70.83% | 95.83% | 70.83% | 29.17% | 13.89% | 100.00% |
| C | 24 | 45.83% | 70.83% | 45.83% | 54.17% | 22.22% | 100.00% |

## Results by task difficulty

| Difficulty | Runs | Success under budget | First choice | Budget exhaustion | Minimal tool set | Parameter accuracy |
|---|---:|---:|---:|---:|---:|---:|
| D1 | 18 | 0.00% | 100.00% | 100.00% | 0.00% | 83.33% |
| D2 | 24 | 54.17% | 62.50% | 41.67% | 54.17% | 95.83% |
| D3 | 30 | 100.00% | 100.00% | 0.00% | 100.00% | 100.00% |

## Paired comparisons

The analysis pairs conditions by task and repetition. The six primary comparisons use two-sided exact McNemar tests with Holm correction. The values below are reported from the frozen Study 2 summary.

| Pair | Metric | Difference (A-B, percentage points) | Discordant pairs | Exact p | Holm-adjusted p |
|---|---|---:|---:|---:|---:|
| A–B | task_success_under_budget | -8.33 | 2 | 0.50000 | 1.00000 |
| A–C | task_success_under_budget | +16.67 | 6 | 0.21875 | 0.65625 |
| B–C | task_success_under_budget | +25.00 | 6 | 0.03125 | 0.18750 |
| A–B | first_choice_accuracy | +0.00 | 2 | 1.00000 | 1.00000 |
| A–C | first_choice_accuracy | +25.00 | 8 | 0.07031 | 0.28125 |
| B–C | first_choice_accuracy | +25.00 | 6 | 0.03125 | 0.18750 |

The descriptive results show the largest difference in D2. The Holm-adjusted primary comparisons do not reach α=0.05; this study therefore does not establish a statistically significant advantage for any condition. D1 has a protocol-related floor effect and D3 is at ceiling, so the overall differences should be interpreted with the difficulty-specific results.

## Scope of the public package

The release includes run-level scores, a coded schedule, event projections, the frozen scoring policy, and hashes for integrity checks. It excludes Ground Truth values, exact task prompts, raw answers, and original execution logs. The public package supports recalculating aggregate statistics and auditing the projected event sequence, but it cannot independently rescore the private raw answers against SAP Ground Truth.
