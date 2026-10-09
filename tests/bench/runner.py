"""Execute a suite: arms x reps, with resume, a hard budget, timeouts and process-tree kill.

Results append to <out_dir>/<suite>/results.jsonl, one JSON row per finished run,
keyed by (arm, rep) so a re-run skips what's already done.
"""

import json
import os
import platform
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel

from tests.bench.collect import collect_run
from tests.bench.config import ARTIFACT_SAFE_KEYS, REPO_ROOT, BenchSettings
from tests.bench.estimate import per_run_estimate
from tests.bench.gates import evaluate
from tests.bench.matrix import Arm, Suite
from tests.bench.prices import PriceTable


class RunOutcome(BaseModel):
    exit_code: int | None
    timed_out: bool
    seconds: float


# (arm, run_dir, env, timeout_s) -> outcome. Injected in tests; real runs use _subprocess_executor.
Executor = Callable[[Arm, Path, dict[str, str], float], RunOutcome]


class BudgetExceededError(Exception):
    pass


def _kill_tree(proc: subprocess.Popen) -> None:
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def _subprocess_executor(
    arm: Arm, run_dir: Path, env: dict[str, str], timeout_s: float
) -> RunOutcome:
    run_dir.mkdir(parents=True, exist_ok=True)
    arm_file = run_dir / "arm.json"
    arm_file.write_text(arm.model_dump_json(indent=2), encoding="utf-8")
    started = time.time()
    with (
        (run_dir / "stdout.log").open("w", encoding="utf-8") as out,
        (run_dir / "stderr.log").open("w", encoding="utf-8") as err,
    ):
        kwargs: dict = {
            "cwd": REPO_ROOT,
            "env": env,
            "stdout": out,
            "stderr": err,
            "stdin": subprocess.DEVNULL,
        }
        if platform.system() != "Windows":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            [sys.executable, "-m", "tests.bench.run_one", str(run_dir), str(arm_file)], **kwargs
        )
        try:
            code = proc.wait(timeout=timeout_s)
            return RunOutcome(exit_code=code, timed_out=False, seconds=time.time() - started)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait(timeout=30)
            return RunOutcome(exit_code=None, timed_out=True, seconds=time.time() - started)


def _executor_for(arm: Arm) -> Executor:
    if arm.kind == "web":
        from tests.bench.web_driver import run_web  # lazy: web_driver imports this module

        return run_web
    return _subprocess_executor


def run_env(
    arm: Arm, run_dir: Path, base_env: dict[str, str], settings: BenchSettings
) -> dict[str, str]:
    """Environment for one run: the caller's env plus a scratch DB and the arm's overrides."""
    env = dict(base_env)
    env.update(
        {
            "DB_PATH": str(run_dir / "paranoid.db"),
            "PYTHONIOENCODING": "utf-8",
            "ANTHROPIC_EFFORT": settings.effort,
            "BENCH_EFFORT": settings.effort,
        }
    )
    if arm.main is not None:
        env["DEFAULT_PROVIDER"] = arm.main.provider
    env.update(arm.env)
    return env


def safe_env_snapshot(env: dict[str, str]) -> dict[str, str]:
    """The allow-listed settings worth recording; never credentials."""
    return {k: env[k] for k in ARTIFACT_SAFE_KEYS if k in env}


def _done_keys(results_path: Path) -> set[tuple[str, int]]:
    if not results_path.is_file():
        return set()
    keys = set()
    for line in results_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("outcome") == "ok" or not row.get("retryable", True):
                keys.add((row["arm"], row["rep"]))
    return keys


def run_suite(
    suite: Suite,
    settings: BenchSettings,
    base_env: dict[str, str],
    prices: PriceTable | None,
    *,
    max_cost: Decimal,
    reps: int | None = None,
    only: str | None = None,
    allow_unpriced: bool = False,
    executor: Executor | None = None,
    log: Callable[[str], None] = print,
) -> list[dict]:
    suite_dir = settings.out_dir / suite.id
    suite_dir.mkdir(parents=True, exist_ok=True)
    results_path = suite_dir / "results.jsonl"
    done = _done_keys(results_path)
    spent = Decimal(0)
    rows = []

    for rep in range(1, (reps or suite.reps) + 1):
        for arm in suite.arms:
            if only and arm.id != only:
                continue
            if (arm.id, rep) in done:
                log(f"skip {arm.id} rep {rep}: already done")
                continue
            estimate = per_run_estimate(arm, prices)
            if estimate is None and not allow_unpriced:
                raise BudgetExceededError(
                    f"{arm.id}: model has no price in the price file (pass --allow-unpriced to run anyway)"
                )
            if estimate is not None and spent + estimate > max_cost:
                raise BudgetExceededError(
                    f"next run {arm.id} rep {rep} (est. {estimate}) would exceed the cap: spent {spent} of {max_cost}"
                )

            run_dir = suite_dir / arm.id / f"rep-{rep}"
            env = run_env(arm, run_dir, base_env, settings)
            timeout_s = settings.run_timeout_s * arm.timeout_factor
            log(
                f"run {arm.id} rep {rep} (est. {estimate if estimate is not None else 'n/a'}; spent so far {spent})"
            )
            outcome = (executor or _executor_for(arm))(arm, run_dir, env, timeout_s)

            row = collect_run(run_dir, arm, prices)
            row.update(
                {
                    "suite": suite.id,
                    "rep": rep,
                    "run_dir": str(run_dir),
                    "timed_out": outcome.timed_out,
                    "settings": safe_env_snapshot(env),
                    "gates": evaluate(row, arm, run_dir),
                }
            )
            gates_ok = all(g["ok"] for g in row["gates"].values())
            row["outcome"] = (
                "timeout"
                if outcome.timed_out
                else ("ok" if outcome.exit_code == 0 and gates_ok else "failed")
            )
            row["retryable"] = row["outcome"] != "ok"
            actual = row.get("cost")
            spent += Decimal(str(actual)) if actual is not None else (estimate or Decimal(0))
            with results_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
            rows.append(row)
            log(
                f"  -> {row['outcome']} in {outcome.seconds:.0f}s, cost {actual if actual is not None else 'n/a'}; "
                f"gates failed: {[k for k, g in row['gates'].items() if not g['ok']] or 'none'}"
            )
    return rows
