"""Turn one finished run directory (scratch DB + run.json + logs + out.json) into a metrics row.

Pure reads of a completed run; safe to re-run on old directories.
"""

import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from backend.scoring.cvss31 import score_and_severity
from tests.bench.matrix import PROBE_TERMS, Arm
from tests.bench.prices import PriceTable, run_cost, step_costs


# Log lines the providers/runner already emit, counted as reliability events.
LOG_PATTERNS = {
    "json_retries": r"failed JSON parsing",
    "auto_bumps": r"auto-bumping to \d+|bumping to \d+",
    "rule_engine_fallback": r"switching to rule-engine-only",
    "forced_tool_fallback": r"rejects forced tool choice",
    "temperature_fallback": r"rejects the `temperature` parameter",
    "prose_retries": r"answered without calling the respond tool",
    "refusals": r"refus(al|ed)",
    "timeouts": r"timed out",
}
_ENRICH = re.compile(r"Enrichment complete: (\d+) attack trees, (\d+) test suites")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _calls(run_dir: Path) -> list[dict]:
    path = run_dir / "calls.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _cvss_check(rows: list[sqlite3.Row]) -> dict:
    with_vector = [r for r in rows if r["cvss_vector"]]
    valid, mismatches = 0, 0
    for r in with_vector:
        try:
            score, severity = score_and_severity(r["cvss_vector"])
        except ValueError:
            continue
        valid += 1
        if (
            r["cvss_score"] is None
            or abs(score - r["cvss_score"]) > 1e-9
            or severity != r["cvss_severity"]
        ):
            mismatches += 1
    return {
        "with_vector": len(with_vector),
        "valid": valid,
        "mismatches": mismatches,
        "distinct_vectors": len({r["cvss_vector"] for r in with_vector}),
    }


def _probe_hits(
    assets: list[sqlite3.Row], flows: list[sqlite3.Row], threats: list[sqlite3.Row]
) -> dict:
    out = {}
    for key, pattern in PROBE_TERMS.items():
        rx = re.compile(pattern, re.I)
        out[key] = {
            "assets": sum(bool(rx.search(a["name"] or "")) for a in assets),
            "flows": sum(
                bool(
                    rx.search(
                        " ".join(
                            str(f[c] or "")
                            for c in ("source_entity", "target_entity", "flow_description")
                        )
                    )
                )
                for f in flows
            ),
            "threats": sum(
                bool(
                    rx.search(" ".join(str(t[c] or "") for c in ("name", "description", "target")))
                )
                for t in threats
            ),
        }
    return out


def collect_run(run_dir: Path, arm: Arm, prices: PriceTable | None) -> dict:
    meta = _read_json(run_dir / "run.json")
    out = _read_json(run_dir / "out.json")
    logs = _read_text(run_dir / "stdout.log") + "\n" + _read_text(run_dir / "stderr.log")
    calls = _calls(run_dir)
    execution = out.get("execution", {})
    events = out.get("events", [])

    row: dict = {
        "arm": arm.id,
        "exit_code": meta.get("exit_code"),
        "error": meta.get("error"),
        "wall_s": round(meta["finished"] - meta["started"], 1) if "finished" in meta else None,
        "pipeline_s": execution.get("duration_seconds"),
        "status": execution.get("status"),
        "iterations": execution.get("iterations_completed"),
        "stopped_reason": execution.get("stopped_reason"),
        "exports": meta.get("exports", {}),
        "web_checks": meta.get("web_checks"),
        "reliability": {k: len(re.findall(p, logs, re.I)) for k, p in LOG_PATTERNS.items()},
        "vision_unsupported_event": any(
            "image" in (e.get("message") or "") and "skipped" in (e.get("message") or "")
            for e in events
        ),
    }

    enrich = _ENRICH.search(logs)
    row["enrich"] = (
        {"attack_trees": int(enrich.group(1)), "test_suites": int(enrich.group(2))}
        if enrich
        else None
    )

    row["calls"] = {
        "count": len(calls),
        "errors": [c["error"] for c in calls if c.get("error")],
        "images_by_response_model": {
            c["response_model"]: c["images"] for c in calls if c["images"]
        },
        "max_diagram_tags": max((len(c.get("diagram_tags", [])) for c in calls), default=0),
    }

    db_path = run_dir / "paranoid.db"
    if not db_path.is_file():
        row["db"] = None
        return row

    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        model = conn.execute(
            "SELECT * FROM threat_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if model is None:
            row["db"] = None
            return row
        mid = model["id"]
        threats = conn.execute("SELECT * FROM threats WHERE model_id = ?", (mid,)).fetchall()
        assets = conn.execute("SELECT * FROM assets WHERE model_id = ?", (mid,)).fetchall()
        flows = conn.execute("SELECT * FROM flows WHERE model_id = ?", (mid,)).fetchall()
        diagrams = conn.execute(
            "SELECT name, kind FROM model_diagrams WHERE model_id = ? ORDER BY position, created_at",
            (mid,),
        ).fetchall()
        deps = conn.execute(
            "SELECT COUNT(*) FROM dependency_scans WHERE model_id = ?", (mid,)
        ).fetchone()[0]

    usage = json.loads(model["usage_summary"]) if model["usage_summary"] else None
    model_to_slot = {}
    for m in (arm.main, arm.fast):
        if m is not None:
            model_to_slot[m.model_id] = m.slot

    sources = Counter(t["source"] for t in threats)
    row["db"] = {
        "model_status": model["status"],
        "threats": len(threats),
        "by_source": dict(sources),
        "stride": dict(Counter(t["stride_category"] for t in threats if t["stride_category"])),
        "maestro": sum(1 for t in threats if t["maestro_category"]),
        "with_attack_techniques": sum(
            1 for t in threats if t["attack_techniques"] not in (None, "", "[]")
        ),
        "cvss": _cvss_check(threats),
        "assets": len(assets),
        "flows": len(flows),
        "diagrams": [(d["name"], d["kind"]) for d in diagrams],
        "dependency_scans": deps,
        "probe_hits": _probe_hits(assets, flows, threats),
    }
    if usage:
        cost = run_cost(usage.get("by_model", []), model_to_slot, prices)
        row["usage"] = {
            "total_tokens": usage.get("total_tokens"),
            "by_model": usage.get("by_model", []),
            "steps": [
                {
                    "step": s["step"],
                    "iteration": s["iteration"],
                    "model": s["model"],
                    "status": s["status"],
                    "duration_ms": s["duration_ms"],
                    "usage": s["usage"],
                }
                for s in usage.get("steps", [])
            ],
            "fast_routing_disabled": usage.get("fast_routing_disabled"),
            "refusal_count": usage.get("refusal_count", 0),
        }
        row["cost"] = float(cost) if cost is not None else None
        row["step_cost"] = {
            k: (float(v) if v is not None else None)
            for k, v in step_costs(usage.get("steps", []), model_to_slot, prices).items()
        }
    else:
        row["usage"], row["cost"], row["step_cost"] = None, None, {}
    return row
