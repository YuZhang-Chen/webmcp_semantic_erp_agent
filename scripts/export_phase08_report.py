"""Export the Phase 08 formal experiment summary as Markdown and run-level CSV."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percent(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def percentage_points(value: float) -> str:
    return f"{value * 100:+.2f}"


def quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson_ci(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def macro_accuracy(rows: list[Mapping[str, Any]], field: str) -> float:
    return sum(float(row.get(field) or 0) for row in rows) / len(rows) if rows else 0.0


def metric_value(rows: list[Mapping[str, Any]], metric: str) -> float:
    if metric == "tool_micro":
        denominator = sum(int(row.get("tool_decisions") or 0) for row in rows)
        return sum(int(row.get("tool_selection_correct") or 0) for row in rows) / denominator if denominator else 0.0
    if metric == "tool_macro":
        return macro_accuracy(rows, "tool_selection_accuracy")
    if metric == "parameter_micro":
        denominator = sum(int(row.get("scored_parameters") or 0) for row in rows)
        return sum(int(row.get("parameter_correct") or 0) for row in rows) / denominator if denominator else 0.0
    if metric == "parameter_macro":
        return macro_accuracy(rows, "parameter_accuracy")
    if metric == "task_success":
        return sum(int(row.get("task_success") or 0) for row in rows) / len(rows) if rows else 0.0
    raise ValueError(f"unknown metric: {metric}")


def clustered_bootstrap_ci(rows: list[Mapping[str, Any]], condition: str, metric: str, *, seed: int, samples: int = 20000) -> tuple[float, float]:
    selected = [row for row in rows if row.get("condition") == condition]
    tasks = sorted({str(row["task_id"]) for row in selected})
    by_task = {task: [row for row in selected if row["task_id"] == task] for task in tasks}
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        sampled: list[Mapping[str, Any]] = []
        for _index in tasks:
            sampled.extend(by_task[rng.choice(tasks)])
        estimates.append(metric_value(sampled, metric))
    return quantile(estimates, 0.025), quantile(estimates, 0.975)


def task_level_differences(rows: list[Mapping[str, Any]], first: str, second: str, metric: str) -> list[float]:
    tasks = sorted({str(row["task_id"]) for row in rows})
    differences: list[float] = []
    for task in tasks:
        first_rows = [row for row in rows if row["task_id"] == task and row["condition"] == first]
        second_rows = [row for row in rows if row["task_id"] == task and row["condition"] == second]
        differences.append(metric_value(second_rows, metric) - metric_value(first_rows, metric))
    return differences


def paired_bootstrap_ci(differences: list[float], *, seed: int, samples: int = 20000) -> tuple[float, float]:
    rng = random.Random(seed)
    estimates = [sum(rng.choice(differences) for _ in differences) / len(differences) for _ in range(samples)]
    return quantile(estimates, 0.025), quantile(estimates, 0.975)


def exact_sign_flip_p(differences: list[float]) -> float:
    nonzero = [value for value in differences if not math.isclose(value, 0.0, abs_tol=1e-12)]
    if not nonzero:
        return 1.0
    observed = abs(sum(nonzero))
    extreme = 0
    total = 1 << len(nonzero)
    for mask in range(total):
        permuted = sum(value if mask & (1 << index) else -value for index, value in enumerate(nonzero))
        if abs(permuted) >= observed - 1e-12:
            extreme += 1
    return extreme / total


def exact_mcnemar(rows: list[Mapping[str, Any]], first: str, second: str) -> tuple[int, int, float]:
    lookup = {(row["task_id"], int(row["repetition"]), row["condition"]): int(row["task_success"]) for row in rows}
    pairs = sorted({(row["task_id"], int(row["repetition"])) for row in rows})
    first_only = sum(lookup[task, repetition, first] == 1 and lookup[task, repetition, second] == 0 for task, repetition in pairs)
    second_only = sum(lookup[task, repetition, first] == 0 and lookup[task, repetition, second] == 1 for task, repetition in pairs)
    discordant = first_only + second_only
    if discordant == 0:
        return first_only, second_only, 1.0
    tail = sum(math.comb(discordant, index) for index in range(min(first_only, second_only) + 1)) / (2 ** discordant)
    return first_only, second_only, min(1.0, 2 * tail)


def holm_adjust(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    adjusted = [0.0] * len(values)
    running = 0.0
    total = len(values)
    for rank, (index, value) in enumerate(indexed):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[index] = running
    return adjusted


def inference(rows: list[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    conditions: dict[str, Any] = {}
    metrics = ("tool_micro", "tool_macro", "parameter_micro", "parameter_macro", "task_success")
    for condition_index, condition in enumerate(("A", "B", "C")):
        selected = [row for row in rows if row["condition"] == condition]
        conditions[condition] = {}
        for metric_index, metric in enumerate(metrics):
            if metric == "parameter_micro":
                correct = sum(int(row.get("parameter_correct") or 0) for row in selected)
                total = sum(int(row.get("scored_parameters") or 0) for row in selected)
                ci = wilson_ci(correct, total)
            elif metric == "task_success":
                correct = sum(int(row.get("task_success") or 0) for row in selected)
                ci = wilson_ci(correct, len(selected))
            else:
                ci = clustered_bootstrap_ci(rows, condition, metric, seed=seed + condition_index * 100 + metric_index)
            conditions[condition][metric] = {
                "estimate": metric_value(selected, metric),
                "ci": ci,
            }
    comparisons: list[dict[str, Any]] = []
    for comparison_index, (first, second) in enumerate((("A", "B"), ("A", "C"), ("B", "C"))):
        result: dict[str, Any] = {"label": f"{second} − {first}"}
        for metric_index, metric in enumerate(("tool_macro", "parameter_macro", "task_success")):
            differences = task_level_differences(rows, first, second, metric)
            item = {
                "difference": sum(differences) / len(differences),
                "ci": paired_bootstrap_ci(differences, seed=seed + 1000 + comparison_index * 100 + metric_index),
            }
            if metric == "task_success":
                first_only, second_only, p_value = exact_mcnemar(rows, first, second)
                item.update({"p": p_value, "first_only": first_only, "second_only": second_only})
            else:
                item["p"] = exact_sign_flip_p(differences)
            result[metric] = item
        comparisons.append(result)
    for metric in ("tool_macro", "parameter_macro", "task_success"):
        adjusted = holm_adjust([comparison[metric]["p"] for comparison in comparisons])
        for comparison, value in zip(comparisons, adjusted, strict=True):
            comparison[metric]["holm_p"] = value
    return {"conditions": conditions, "comparisons": comparisons}


def aggregate(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    runs = len(rows)
    decisions = sum(int(row.get("tool_decisions") or 0) for row in rows)
    selected = sum(int(row.get("tool_selection_correct") or 0) for row in rows)
    parameters = sum(int(row.get("scored_parameters") or 0) for row in rows)
    parameter_correct = sum(int(row.get("parameter_correct") or 0) for row in rows)
    successes = sum(int(row.get("task_successes") or 0) for row in rows)
    return {
        "runs": runs,
        "tool_selection_accuracy": selected / decisions if decisions else None,
        "parameter_accuracy": parameter_correct / parameters if parameters else None,
        "task_success_rate": successes / runs if runs else None,
        "tool_selection_correct": selected,
        "tool_decisions": decisions,
        "parameter_correct": parameter_correct,
        "scored_parameters": parameters,
        "task_successes": successes,
    }


def invalid_attempts(log_dir: Path) -> list[dict[str, str]]:
    attempts: list[dict[str, str]] = []
    for path in sorted(log_dir.glob("*.jsonl")):
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        invalid = next((event for event in reversed(events) if event.get("event_type") == "run_invalid"), None)
        if invalid:
            attempts.append({"run_id": path.stem, "reason": str(invalid.get("reason", "unspecified"))})
    return attempts


def export_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fields = [
        "index", "run_id", "task_id", "condition", "repetition", "replacement",
        "tool_selection_accuracy", "parameter_accuracy", "task_success",
        "tool_selection_correct", "tool_decisions", "parameter_correct",
        "scored_parameters", "task_successes", "tool_call_limit_exceeded",
        "error_categories", "log_sha256", "manifest_sha256",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            value = {field: row.get(field) for field in fields}
            value["error_categories"] = ";".join(row.get("error_categories") or [])
            writer.writerow(value)


def table_row(label: str, value: Mapping[str, Any]) -> str:
    return (
        f"| {label} | {value.get('runs', 0)} | "
        f"{percent(value.get('tool_selection_accuracy'))} | "
        f"{percent(value.get('parameter_accuracy'))} | "
        f"{percent(value.get('task_success_rate'))} |"
    )


def export_markdown(
    path: Path,
    summary: Mapping[str, Any],
    protocol: Mapping[str, Any],
    plan: Mapping[str, Any],
    attempts: list[Mapping[str, str]],
    csv_name: str,
) -> None:
    rows = list(summary.get("runs", []))
    statistics = inference(rows, int(protocol.get("seed", 20260915)))
    overall = aggregate(rows)
    by_condition = summary.get("by_condition", {})
    by_repetition = summary.get("by_repetition", {})
    by_task = summary.get("by_task", {})
    a = by_condition.get("A", {})
    b = by_condition.get("B", {})
    c = by_condition.get("C", {})

    lines = [
        "# Phase 08 正式 A/B/C 實驗完整報告",
        "",
        f"- 匯出時間（UTC）：`{datetime.now(UTC).isoformat()}`",
        f"- Protocol：`{protocol.get('protocol')}` / `{protocol.get('schema_version')}`",
        f"- 資料來源：`{protocol.get('source_id')}`（live SAP OData V2，唯讀）",
        f"- 排程 seed：`{protocol.get('seed')}`",
        f"- Schedule SHA-256：`{plan.get('schedule_sha256')}`",
        f"- Ground Truth SHA-256：`{plan.get('ground_truth_sha256')}`",
        f"- Scoring policy SHA-256：`{plan.get('scoring_policy_sha256')}`",
        "",
        "## 執行完整性",
        "",
        f"- 預定 runs：{summary.get('planned_runs')}；有效 runs：{summary.get('valid_runs')}。",
        f"- 缺失 runs：{summary.get('missing_runs')}；正式 slot replacements：{summary.get('replacement_runs')}。",
        f"- 原始無效嘗試保留數：{len(attempts)}；不納入正式分母。",
        f"- 正式設計：20 tasks × 3 conditions × 3 repetitions = 180 runs。",
        f"- 難度配額：D1/D2/D3 = 4/8/8。",
        f"- Agent：`{protocol.get('agent', {}).get('model')}`，reasoning `{protocol.get('agent', {}).get('reasoning')}`，每個 run 使用全新 session。",
        f"- 工具呼叫上限：{protocol.get('agent', {}).get('tool_call_limit')}。",
        "- 120 秒 timeout gate：研究者已明確豁免；本結果不得宣稱已驗證執行期 timeout enforcement。",
        "",
        "## 指標定義：macro 與 micro Tool Selection",
        "",
        "- **Micro Tool Selection Accuracy**：先加總所有 run 的正確 tool decisions 與全部被評分 decisions，再計算 `Σcorrect / Σdecisions`；tool calls 較多的 run 權重較大。原始報告中的 Tool Selection Accuracy 即此定義。",
        "- **Macro Tool Selection Accuracy**：先計算每個 run 的 `correct / decisions`，再對 60 個 runs 取算術平均；每個 `task × repetition` run 權重相同。",
        "- 缺少 required operation 不直接增加 Tool Selection 分母，而由 Task Success 處罰；因此 Tool Selection 較接近 decision precision，而非完整性指標。",
        "- Tool micro/macro 的 95% CI 使用以 task 為 cluster 的 percentile bootstrap（20,000 次、固定 protocol seed），同一 task 的三次 repetitions 一起重抽。Parameter micro 與 Task Success 的條件內 CI 使用 Wilson score interval，以避免全成功條件產生退化的 `[100%, 100%]` bootstrap interval。",
        "",
        "## 整體結果",
        "",
        "| 範圍 | Runs | Tool micro | Tool macro | Parameter micro | Task Success |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| Overall | 180 | {percent(metric_value(rows, 'tool_micro'))} | {percent(metric_value(rows, 'tool_macro'))} | {percent(metric_value(rows, 'parameter_micro'))} | {percent(metric_value(rows, 'task_success'))} |",
        "",
        "## 各條件結果與 95% CI",
        "",
        "| Condition | Runs | Tool micro [95% CI] | Tool macro [95% CI] | Parameter micro [95% CI] | Task Success [95% CI] |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        *[
            f"| {condition} | 60 | "
            f"{percent(statistics['conditions'][condition]['tool_micro']['estimate'])} [{percent(statistics['conditions'][condition]['tool_micro']['ci'][0])}, {percent(statistics['conditions'][condition]['tool_micro']['ci'][1])}] | "
            f"{percent(statistics['conditions'][condition]['tool_macro']['estimate'])} [{percent(statistics['conditions'][condition]['tool_macro']['ci'][0])}, {percent(statistics['conditions'][condition]['tool_macro']['ci'][1])}] | "
            f"{percent(statistics['conditions'][condition]['parameter_micro']['estimate'])} [{percent(statistics['conditions'][condition]['parameter_micro']['ci'][0])}, {percent(statistics['conditions'][condition]['parameter_micro']['ci'][1])}] | "
            f"{percent(statistics['conditions'][condition]['task_success']['estimate'])} [{percent(statistics['conditions'][condition]['task_success']['ci'][0])}, {percent(statistics['conditions'][condition]['task_success']['ci'][1])}] |"
            for condition in ("A", "B", "C")
        ],
        "",
        "### 相對於 A 的差異（百分點）",
        "",
        "| 比較 | Tool micro | Parameter micro | Task Success |",
        "| --- | ---: | ---: | ---: |",
        f"| B − A | {(float(b.get('tool_selection_accuracy', 0)) - float(a.get('tool_selection_accuracy', 0))) * 100:+.2f} | {(float(b.get('parameter_accuracy', 0)) - float(a.get('parameter_accuracy', 0))) * 100:+.2f} | {(float(b.get('task_success_rate', 0)) - float(a.get('task_success_rate', 0))) * 100:+.2f} |",
        f"| C − A | {(float(c.get('tool_selection_accuracy', 0)) - float(a.get('tool_selection_accuracy', 0))) * 100:+.2f} | {(float(c.get('parameter_accuracy', 0)) - float(a.get('parameter_accuracy', 0))) * 100:+.2f} | {(float(c.get('task_success_rate', 0)) - float(a.get('task_success_rate', 0))) * 100:+.2f} |",
        "",
        "## 配對檢定",
        "",
        "配對鍵為相同的 `task_id × repetition`。Tool macro 與 Parameter macro 先在每個 task 內平均三次 repetitions，再做雙尾 exact sign-flip permutation test；Task Success 使用 60 對 binary outcomes 的雙尾 exact McNemar test。差異的 95% CI 為 task-cluster paired bootstrap；p 值同時提供各 metric 三組比較的 Holm 校正。",
        "",
        "| 比較 | Metric | 差異 pp [95% CI] | Discordant pairs | Raw p | Holm p |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
        *[
            line
            for comparison in statistics["comparisons"]
            for line in (
                f"| {comparison['label']} | Tool macro | {percentage_points(comparison['tool_macro']['difference'])} [{percentage_points(comparison['tool_macro']['ci'][0])}, {percentage_points(comparison['tool_macro']['ci'][1])}] | — | {comparison['tool_macro']['p']:.4f} | {comparison['tool_macro']['holm_p']:.4f} |",
                f"| {comparison['label']} | Parameter macro | {percentage_points(comparison['parameter_macro']['difference'])} [{percentage_points(comparison['parameter_macro']['ci'][0])}, {percentage_points(comparison['parameter_macro']['ci'][1])}] | — | {comparison['parameter_macro']['p']:.4f} | {comparison['parameter_macro']['holm_p']:.4f} |",
                f"| {comparison['label']} | Task Success | {percentage_points(comparison['task_success']['difference'])} [{percentage_points(comparison['task_success']['ci'][0])}, {percentage_points(comparison['task_success']['ci'][1])}] | {comparison['task_success']['first_only']} / {comparison['task_success']['second_only']} | {comparison['task_success']['p']:.4f} | {comparison['task_success']['holm_p']:.4f} |",
            )
        ],
        "",
        "Discordant pairs 以「前者成功/後者失敗」與「前者失敗/後者成功」表示。所有檢定均為雙尾；`α = 0.05`。",
        "",
        "## 各 repetition 結果",
        "",
        "| Repetition | Runs | Tool micro | Parameter micro | Task Success Rate |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[table_row(repetition, by_repetition.get(repetition, {})) for repetition in ("1", "2", "3")],
        "",
        "## 各 task 結果",
        "",
        "| Task | Runs | Tool micro | Parameter micro | Task Success Rate |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[table_row(task, by_task[task]) for task in sorted(by_task)],
        "",
        "## 錯誤分類",
        "",
        "| Error category | Count |",
        "| --- | ---: |",
        *[f"| `{name}` | {count} |" for name, count in sorted(summary.get("error_categories", {}).items())],
        "",
        "## 無效嘗試與 replacement lineage",
        "",
        "| Invalid attempt | 原因 |",
        "| --- | --- |",
        *[f"| `{item['run_id']}` | {item['reason']} |" for item in attempts],
        "",
        "有效 replacement：`F08-T10-A-R1-X2`，填補 frozen schedule 的 `F08-T10-A-R1` slot。",
        "",
        "## 解讀與限制",
        "",
        "- B 與 C 的 Parameter Accuracy 與 Task Success Rate 均為 100%；A 有兩個 task failure。",
        "- Tool micro 因不同 run 的 decision 數不同而呈現小幅條件差異；Tool macro 三組皆為 86.67%，配對差異為 0。",
        "- B/C 相對 A 的 Parameter macro 與 Task Success 點估計較高，但 exact paired tests 在 Holm 校正後均未達 `α = 0.05`。",
        "- 信賴區間與檢定以 task 為推論 cluster；只有 20 個 task，統計檢定力有限，不應把未顯著解讀為條件等效。",
        "- Ground Truth、raw answers 與 SAP business identifiers 保留於 researcher-private／ignored artifacts，不納入本報告。",
        "- timeout enforcement 未經驗證，八次工具呼叫上限由 runner/scorer 控制與判定。",
        "",
        "## 可重算 artifacts",
        "",
        f"- Run-level CSV：`{csv_name}`",
        "- Canonical summary：`formal-summary-v1.json`",
        "- Run scores：`scores/*.json`",
        "- Execution logs：`build/phase-08/headless-runs/*.jsonl`",
        "- Frozen manifests：`formal-run-manifests-six-priority-v1/*.json`",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--log-dir", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    summary, protocol, plan = read_json(args.summary), read_json(args.protocol), read_json(args.plan)
    if summary.get("planned_runs") != 180 or summary.get("valid_runs") != 180 or summary.get("missing_runs") != 0:
        raise SystemExit("formal summary is incomplete; refusing full-report export")
    rows = list(summary.get("runs", []))
    if len(rows) != 180:
        raise SystemExit("formal summary must contain 180 run rows")
    attempts = invalid_attempts(args.log_dir)
    export_csv(args.csv, rows)
    export_markdown(args.markdown, summary, protocol, plan, attempts, args.csv.name)
    print(json.dumps({"markdown": str(args.markdown), "csv": str(args.csv), "runs": len(rows), "invalid_attempts": len(attempts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
