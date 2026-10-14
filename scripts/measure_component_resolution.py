"""Measure how many flow/boundary endpoints and threat targets resolve to assets.

Read-only: opens the DB with mode=ro. Point it at a COPY of a database, not the
live one (a WAL-mode DB needs its -wal/-shm files copied too).

    python scripts/measure_component_resolution.py data-copy.db [--list-unresolved]

Reports, per tier and in total: flow endpoints, trust-boundary endpoints, and
LLM threat targets (rule-engine and dependency targets such as "lodash@4" are
not expected to name an asset, so they are reported separately).
"""

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.nodes.entities import resolve_asset_with_tier


def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.0f}%)" if whole else "n/a"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--list-unresolved", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # category -> Counter(tier); tier 0 = unresolved
    tiers: dict[str, Counter] = {}
    unresolved: list[tuple[str, str]] = []
    skipped_models = 0

    for model in conn.execute("SELECT id FROM threat_models"):
        mid = model["id"]
        assets = [
            (r["id"], r["name"])
            for r in conn.execute("SELECT id, name FROM assets WHERE model_id = ?", (mid,))
        ]
        if not assets:
            skipped_models += 1
            continue

        def record(category: str, text: str, assets: list = assets) -> None:
            _, tier = resolve_asset_with_tier(text or "", assets)
            tiers.setdefault(category, Counter())[tier] += 1
            if tier == 0:
                unresolved.append((category, text or ""))

        for table, label in (
            ("flows", "flow endpoints"),
            ("trust_boundaries", "boundary endpoints"),
        ):
            for r in conn.execute(
                f"SELECT source_entity, target_entity FROM {table} WHERE model_id = ?", (mid,)
            ):
                record(label, r["source_entity"])
                record(label, r["target_entity"])
        for r in conn.execute("SELECT target, source FROM threats WHERE model_id = ?", (mid,)):
            record(
                "LLM threat targets" if r["source"] == "llm" else "other threat targets",
                r["target"],
            )

    print(f"{args.db}: {skipped_models} model(s) with no assets skipped")
    for category, counter in sorted(tiers.items()):
        total = sum(counter.values())
        resolved = total - counter[0]
        by_tier = ", ".join(f"tier {t}: {counter[t]}" for t in (1, 2, 3))
        print(f"  {category:24} {_pct(resolved, total):>14}   {by_tier}, unresolved: {counter[0]}")
    if args.list_unresolved:
        print("\nUnresolved:")
        for category, text in unresolved:
            print(f"  [{category}] {text[:100]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
