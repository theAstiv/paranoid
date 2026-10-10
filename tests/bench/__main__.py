"""`python -m tests.bench <command>`: list | plan | run | report | spike | spotcheck.

Nothing makes a live call except `run` and `spike`, and both print what they're
about to do and require --yes. `run` also requires a spend cap.
"""

import argparse
import os
import sys
from decimal import Decimal

from tests.bench.config import SLOTS, load_settings, merged_env, resolve_slot
from tests.bench.estimate import estimate_suite
from tests.bench.matrix import EXTERNAL_SUITES, build_suites
from tests.bench.prices import load_prices


# boto3 reads credentials from os.environ / the profile chain, not from our merged
# dict. Pipeline runs get the merged env in their subprocess, but `spike` calls
# boto3 in this process, so copy the AWS settings from bench.env across first.
_AWS_KEYS = (
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


def _export_aws_settings(env: dict[str, str]) -> None:
    for key in _AWS_KEYS:
        if env.get(key) and not os.environ.get(key):
            os.environ[key] = env[key]


def _context():
    env = merged_env()
    _export_aws_settings(env)
    settings = load_settings(env)
    return env, settings, build_suites(env, settings), load_prices(settings.prices_file)


def _selected(suites: dict, names: list[str]) -> list:
    if names == ["all"]:
        return list(suites.values())
    unknown = [n for n in names if n not in suites]
    if unknown:
        sys.exit(f"unknown suite(s): {unknown}; see `python -m tests.bench list`")
    return [suites[n] for n in names]


def cmd_list(args) -> None:
    env, settings, suites, prices = _context()
    print("Model slots:")
    for name, slot in SLOTS.items():
        m = resolve_slot(name, env)
        print(
            f"  {name:<14} {('set: ' + m.model_id + (' (images)' if m.images else ' (text-only)')) if m else 'not set (' + slot.env_var + ')'}"
        )
    print(
        f"\nPrice file: {settings.prices_file or 'not set'} ({'loaded' if prices else 'missing'})"
    )
    print("\nLLM suites:")
    for s in suites.values():
        print(f"  {s.id:<20} {len(s.arms)} arm(s) x {s.reps} rep(s)  {s.title}")
        for why in s.skipped:
            print(f"  {'':<20}   skipped: {why}")
    print("\nNo-LLM suites (run directly):")
    for k, v in EXTERNAL_SUITES.items():
        print(f"  {k:<20} {v}")


def cmd_plan(args) -> None:
    _env, _settings, suites, prices = _context()
    grand, unknown = Decimal(0), False
    print("| Suite | Arm | Pipeline runs | Est. input tok | Est. output tok | Est. cost |")
    print("|---|---|---|---|---|---|")
    for suite in _selected(suites, args.suites):
        for est in estimate_suite(suite, prices, args.reps):
            cost = "n/a (unpriced)" if est.cost is None else f"{est.cost}"
            unknown |= est.cost is None
            grand += est.cost or 0
            print(
                f"| {suite.id} | {est.arm} | {est.runs} | {est.input_tokens:,} | {est.output_tokens:,} | {cost} |"
            )
    print(
        f"\nEstimated total: {grand}{' + unpriced arms' if unknown else ''} (includes a 25% margin; real runs vary +-50%)."
    )


def cmd_run(args) -> None:
    from tests.bench.runner import BudgetExceededError, run_suite

    env, settings, suites, prices = _context()
    cap = args.max_cost if args.max_cost is not None else settings.max_cost_usd
    if cap is None:
        sys.exit("set BENCH_MAX_COST_USD or pass --max-cost")
    selected = _selected(suites, args.suites)
    if not args.yes:
        sys.exit("this makes live, billed calls; re-run with --yes after reviewing `plan`")
    remaining = Decimal(str(cap))
    for suite in selected:
        try:
            rows = run_suite(
                suite,
                settings,
                env,
                prices,
                max_cost=remaining,
                reps=args.reps,
                only=args.only,
                allow_unpriced=args.allow_unpriced,
            )
        except BudgetExceededError as exc:
            sys.exit(f"stopped: {exc}")
        remaining -= sum(Decimal(str(r["cost"])) for r in rows if r.get("cost") is not None)


def cmd_report(args) -> None:
    from tests.bench.report import write_report

    _env, settings, suites, _prices = _context()
    names = list(suites) if args.suites == ["all"] else args.suites
    for name in names:
        print(write_report(settings.out_dir, name))


def cmd_spike(args) -> None:
    from tests.bench.spike import run_spike

    env, settings, _suites, _prices = _context()
    models = [m for name in SLOTS if (m := resolve_slot(name, env)) and m.provider == "bedrock"]
    if not models:
        sys.exit("no Bedrock model slots set in bench.env")
    print(f"spike: {len(models)} model(s), ~10 tiny calls each: {[m.slot for m in models]}")
    if not args.yes:
        sys.exit("re-run with --yes to make these calls")
    print(
        run_spike(models, env.get("AWS_REGION", ""), env.get("AWS_PROFILE", ""), settings.out_dir)
    )


def cmd_spotcheck(args) -> None:
    from tests.bench.quality import write_spotcheck_sheet

    _env, settings, _suites, _prices = _context()
    run_dirs = sorted((settings.out_dir / args.suite).glob("*/rep-*"))
    run_dirs = [d for d in run_dirs if (d / "paranoid.db").is_file()]
    out = settings.out_dir / f"{args.suite}-spotcheck.csv"
    print(write_spotcheck_sheet(run_dirs, out, per_run=args.per_run))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tests.bench")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("plan")
    p.add_argument("suites", nargs="+")
    p.add_argument("--reps", type=int)
    p.set_defaults(fn=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("suites", nargs="+")
    r.add_argument("--reps", type=int)
    r.add_argument("--only", help="run a single arm id")
    r.add_argument("--max-cost", type=float)
    r.add_argument("--allow-unpriced", action="store_true")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(fn=cmd_run)
    rep = sub.add_parser("report")
    rep.add_argument("suites", nargs="+")
    rep.set_defaults(fn=cmd_report)
    sp = sub.add_parser("spike")
    sp.add_argument("--yes", action="store_true")
    sp.set_defaults(fn=cmd_spike)
    sc = sub.add_parser("spotcheck")
    sc.add_argument("suite")
    sc.add_argument("--per-run", type=int, default=10)
    sc.set_defaults(fn=cmd_spotcheck)
    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
