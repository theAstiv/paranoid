"""Aggregate a suite's results.jsonl into a Markdown report (median, min-max, n; never a lone mean)."""

import json
import statistics
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from tests.bench.config import REPO_ROOT


def load_rows(results_path: Path) -> list[dict]:
    if not results_path.is_file():
        return []
    return [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return "unknown"


def spread(values: list[float]) -> str:
    """'median [min-max] (n)' for the numbers present; '-' when there are none."""
    vals = [v for v in values if v is not None]
    if not vals:
        return "-"
    med = statistics.median(vals)
    if len(vals) == 1:
        return f"{med:g} (n=1)"
    return f"{med:g} [{min(vals):g}-{max(vals):g}] (n={len(vals)})"


def _db(row: dict, key: str):
    return (row.get("db") or {}).get(key)


def _step_table(by_arm: dict[str, list[dict]]) -> list[str]:
    arms = list(by_arm)
    if len(arms) != 2:
        return []
    a, b = arms
    steps = sorted(
        {s for rows in by_arm.values() for r in rows for s in (r.get("step_cost") or {})}
    )
    lines = [
        f"| Step | {a}: cost/run | {b}: cost/run | Change | {a}: median s | {b}: median s |",
        "|---|---|---|---|---|---|",
    ]
    for step in steps:
        costs, secs = {}, {}
        for arm in arms:
            per_run = [r["step_cost"].get(step) for r in by_arm[arm] if r.get("step_cost")]
            costs[arm] = (
                statistics.median([c for c in per_run if c is not None])
                if any(c is not None for c in per_run)
                else None
            )
            durations = [
                sum(
                    s["duration_ms"]
                    for s in (r.get("usage") or {}).get("steps", [])
                    if s["step"] == step
                )
                / 1000
                for r in by_arm[arm]
                if r.get("usage")
            ]
            secs[arm] = statistics.median(durations) if durations else None
        change = "-"
        if costs[a] and costs[b] is not None:
            change = f"{(costs[b] - costs[a]) / costs[a] * 100:+.0f}%"
        fmt = lambda v, p: f"{v:.{p}f}" if v is not None else "-"  # noqa: E731
        lines.append(
            f"| `{step}` | {fmt(costs[a], 4)} | {fmt(costs[b], 4)} | {change} | {fmt(secs[a], 1)} | {fmt(secs[b], 1)} |"
        )
    return lines


def render(suite_id: str, rows: list[dict]) -> str:
    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)

    out = [
        f"# {suite_id} - {datetime.now(UTC).date().isoformat()}",
        "",
        f"Commit `{_git_commit()}` · {len(rows)} runs · values are median [min-max] (n).",
        "Costs are token counts x the price file; Bedrock has no prompt-cache discount in Paranoid today.",
        "",
        "## Outcomes and gates",
        "",
    ]
    gate_names = sorted({g for r in rows for g in (r.get("gates") or {})})
    if gate_names:
        out.append("| Arm | Runs | ok / failed / timeout | " + " | ".join(gate_names) + " |")
        out.append("|---|---|---|" + "---|" * len(gate_names))
    else:
        out.append("| Arm | Runs | ok / failed / timeout |")
        out.append("|---|---|---|")
    for arm, arm_rows in by_arm.items():
        counts = [sum(r.get("outcome") == o for r in arm_rows) for o in ("ok", "failed", "timeout")]
        cells = []
        for g in gate_names:
            passed = sum(1 for r in arm_rows if (r.get("gates") or {}).get(g, {}).get("ok"))
            cells.append(f"{passed}/{len(arm_rows)}")
        out.append(
            f"| {arm} | {len(arm_rows)} | {counts[0]} / {counts[1]} / {counts[2]} | "
            + " | ".join(cells)
            + (" |" if cells else "")
        )

    out += [
        "",
        "## Measurements",
        "",
        "| Arm | Wall s | Cost | Tokens | Iterations | Threats | LLM / rules / deps | Assets | Flows |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for arm, arm_rows in by_arm.items():
        src = [(_db(r, "by_source") or {}) for r in arm_rows]
        out.append(
            f"| {arm} | {spread([r.get('wall_s') for r in arm_rows])} | {spread([r.get('cost') for r in arm_rows])} | "
            f"{spread([(r.get('usage') or {}).get('total_tokens') for r in arm_rows])} | {spread([r.get('iterations') for r in arm_rows])} | "
            f"{spread([_db(r, 'threats') for r in arm_rows])} | "
            f"{spread([s.get('llm') for s in src])} / {spread([s.get('rule_engine') for s in src])} / {spread([s.get('dependency') for s in src])} | "
            f"{spread([_db(r, 'assets') for r in arm_rows])} | {spread([_db(r, 'flows') for r in arm_rows])} |"
        )

    out += [
        "",
        "## Reliability (totals across runs)",
        "",
        "| Arm | "
        + " | ".join(
            [
                "json_retries",
                "auto_bumps",
                "rule_engine_fallback",
                "forced_tool_fallback",
                "refusals",
                "timeouts",
            ]
        )
        + " |",
        "|---|" + "---|" * 6,
    ]
    for arm, arm_rows in by_arm.items():
        totals = [
            sum((r.get("reliability") or {}).get(k, 0) for r in arm_rows)
            for k in (
                "json_retries",
                "auto_bumps",
                "rule_engine_fallback",
                "forced_tool_fallback",
                "refusals",
                "timeouts",
            )
        ]
        out.append(f"| {arm} | " + " | ".join(str(t) for t in totals) + " |")

    out += [
        "",
        "## Image-only / flow-only components (runs with a hit)",
        "",
        "| Arm | Secrets manager as asset | ...in any flow/threat | Dead-letter queue as asset or flow |",
        "|---|---|---|---|",
    ]
    for arm, arm_rows in by_arm.items():
        hits = [(_db(r, "probe_hits") or {}) for r in arm_rows]
        sm_asset = sum(1 for h in hits if h.get("secrets_manager", {}).get("assets"))
        sm_any = sum(
            1
            for h in hits
            if h.get("secrets_manager", {}).get("flows")
            or h.get("secrets_manager", {}).get("threats")
        )
        dlq = sum(
            1
            for h in hits
            if h.get("dead_letter_queue", {}).get("assets")
            or h.get("dead_letter_queue", {}).get("flows")
        )
        out.append(
            f"| {arm} | {sm_asset}/{len(arm_rows)} | {sm_any}/{len(arm_rows)} | {dlq}/{len(arm_rows)} |"
        )

    step_lines = _step_table(by_arm)
    if step_lines:
        out += ["", "## Per-step comparison (median cost and duration per run)", "", *step_lines]

    failures = [
        (r["arm"], r["rep"], k, g["detail"])
        for r in rows
        for k, g in (r.get("gates") or {}).items()
        if not g["ok"]
    ]
    if failures:
        out += ["", "## Gate failures", ""] + [
            f"- `{a}` rep {rep}, **{k}**: {d}" for a, rep, k, d in failures
        ]
    return "\n".join(out) + "\n"


def write_report(out_dir: Path, suite_id: str) -> Path:
    rows = load_rows(out_dir / suite_id / "results.jsonl")
    path = out_dir / f"{suite_id}-{datetime.now(UTC).date().isoformat()}.md"
    path.write_text(render(suite_id, rows), encoding="utf-8")
    return path
