"""Threat-model quality against the reviewed MediaDrop reference checklist.

Deterministic and model-neutral: embeddings (the same fastembed model the rule
engine uses), not an LLM judge. The threshold must be calibrated on hand-graded
runs before recall is reported; the checklist file records whether it has been.
"""

import csv
import json
import math
import random
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel

from tests.bench.config import BENCH_DIR


CHECKLIST = BENCH_DIR / "fixtures" / "mediadrop-checklist.json"
Embed = Callable[[str], list[float]]


class ItemMatch(BaseModel):
    item_id: str
    title: str
    best_threat: str | None
    score: float
    matched: bool


def load_checklist(path: Path = CHECKLIST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def match_threats(
    threats: list[tuple[str, str]], checklist: dict, embed: Embed, threshold: float | None = None
) -> list[ItemMatch]:
    """Best generated threat per checklist item. `threats` is [(name, description)]."""
    limit = threshold if threshold is not None else checklist["match"]["threshold"]
    threat_vecs = [(name, embed(f"{name}. {desc}")) for name, desc in threats]
    results = []
    for item in checklist["items"]:
        vec = embed(f"{item['title']}. {item['description']}")
        best_name, best = None, 0.0
        for name, tvec in threat_vecs:
            score = _cosine(vec, tvec)
            if score > best:
                best_name, best = name, score
        results.append(
            ItemMatch(
                item_id=item["id"],
                title=item["title"],
                best_threat=best_name,
                score=round(best, 4),
                matched=best_name is not None and best > 0 and best >= limit,
            )
        )
    return results


def run_threats(run_dir: Path) -> list[tuple[str, str]]:
    db = run_dir / "paranoid.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        mid = conn.execute(
            "SELECT id FROM threat_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
        return [
            (n, d or "")
            for n, d in conn.execute(
                "SELECT name, description FROM threats WHERE model_id = ?", (mid,)
            )
        ]


def default_embed() -> Embed:
    from backend.db.vectors import embed_text

    return embed_text


def write_spotcheck_sheet(
    run_dirs: list[Path], out_csv: Path, per_run: int = 10, seed: int = 7
) -> Path:
    """A blinded CSV for the human spot-check: random threats per run, run identity hidden."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    key = {}
    rows = []
    for i, run_dir in enumerate(run_dirs):
        blind = f"R{i + 1:02d}"
        key[blind] = str(run_dir)
        threats = run_threats(run_dir)
        for name, desc in rng.sample(threats, min(per_run, len(threats))):
            rows.append(
                {"run": blind, "threat": name, "description": desc, "keep (y/n)": "", "notes": ""}
            )
    rng.shuffle(rows)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["run", "threat", "description", "keep (y/n)", "notes"]
        )
        writer.writeheader()
        writer.writerows(rows)
    out_csv.with_suffix(".key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    return out_csv
