"""Measure the MAESTRO applicability tagger on saved models (read-only).

    python scripts/measure_maestro_applicability.py data-copy.db [--list]

Per MAESTRO/hybrid model: assets tagged, the applicable set, and the key
sanity check: categories where the LLM produced threats although the tagger
said N/A (a possible missed tag). For other frameworks it reports only how many
assets get any tag, as a false-positive signal on non-AI systems.
"""

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.nodes.maestro_tags import applicable_categories, tag_asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", type=Path)
    parser.add_argument("--list", action="store_true", help="print every tagged asset")
    args = parser.parse_args()

    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    for model in conn.execute("SELECT id, title, framework FROM threat_models"):
        assets = [
            (r["name"], r["description"] or "")
            for r in conn.execute(
                "SELECT name, description FROM assets WHERE model_id = ?", (model["id"],)
            )
        ]
        if not assets:
            continue
        tagged = [(n, tag_asset(n, d)) for n, d in assets]
        applicable = applicable_categories(assets)
        is_maestro = str(model["framework"]).upper() in ("MAESTRO", "HYBRID")
        line = f"{model['framework']:<7} {model['title'][:40]:<40} assets={len(assets):<3} tagged={sum(1 for _, t in tagged if t):<3}"
        if is_maestro:
            produced = Counter(
                r[0]
                for r in conn.execute(
                    "SELECT maestro_category FROM threats WHERE model_id = ? AND maestro_category IS NOT NULL",
                    (model["id"],),
                )
            )
            missed = {c: n for c, n in produced.items() if c not in {a.value for a in applicable}}
            line += f" applicable={[a.value for a in applicable]} threats_in_NA={missed}"
            if not produced:
                line += "  (no categorised threats saved: the N/A check proves nothing)"
        print(line)
        if args.list:
            for n, t in tagged:
                if t:
                    print(f"    {n[:50]:<50} {[c.value for c in t]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
