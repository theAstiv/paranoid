"""E2E pass/fail gates. Each takes (metrics row, arm, run_dir) and returns (ok, detail)."""

import json
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

from tests.bench.matrix import DIAGRAMS, Arm


# The 7 dependency threats the demo manifest produced in every run so far
# (6 of 6 runs, measured 2026-10-01). A different count is a real change worth a look.
EXPECTED_DEPENDENCY_THREATS = 7

Gate = Callable[[dict, Arm, Path], tuple[bool, str]]


def completed(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    db = row.get("db") or {}
    ok = (
        row.get("exit_code") == 0
        and row.get("status") == "completed"
        and db.get("model_status") == "completed"
    )
    return (
        ok,
        f"exit={row.get('exit_code')} status={row.get('status')} db={db.get('model_status')} error={row.get('error')}",
    )


def no_rule_engine_fallback(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    rel = row.get("reliability", {})
    usage = row.get("usage") or {}
    ok = rel.get("rule_engine_fallback", 0) == 0 and not usage.get("fast_routing_disabled")
    return (
        ok,
        f"fallback lines={rel.get('rule_engine_fallback', 0)} fast_routing_disabled={usage.get('fast_routing_disabled')}",
    )


def rule_engine_fallback_reported(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    db = row.get("db") or {}
    by_source = db.get("by_source", {})
    ok = (
        row.get("reliability", {}).get("rule_engine_fallback", 0) > 0
        and by_source.get("llm", 0) == 0
        and db.get("threats", 0) > 0
    )
    return (
        ok,
        f"fallback lines={row.get('reliability', {}).get('rule_engine_fallback', 0)} by_source={by_source}",
    )


def sources_present(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    by_source = (row.get("db") or {}).get("by_source", {})
    problems = []
    if by_source.get("llm", 0) == 0:
        problems.append("no LLM threats")
    if by_source.get("rule_engine", 0) == 0:
        problems.append("no rule-engine threats")
    if (
        arm.inputs in ("full", "full_no_diagrams")
        and by_source.get("dependency", 0) != EXPECTED_DEPENDENCY_THREATS
    ):
        problems.append(
            f"dependency threats {by_source.get('dependency', 0)} != {EXPECTED_DEPENDENCY_THREATS}"
        )
    return not problems, f"by_source={by_source} {'; '.join(problems)}".strip()


def images_match_capability(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    sent = row.get("calls", {}).get("images_by_response_model", {})
    has_png = arm.inputs in ("full", "diagrams_only") and any(d.suffix == ".png" for d in DIAGRAMS)
    if not has_png:
        return not sent, f"no image input; images sent={sent}"
    if arm.images_sent:
        expected = {"SummaryState", "AssetsList", "FlowsList"}
        missing = sorted(expected - set(sent))
        extra = sorted(set(sent) - expected)
        ok = not missing and not extra and all(n == 1 for n in sent.values())
        return ok, f"images per call={sent} missing={missing} unexpected={extra}"
    ok = not sent and row.get("vision_unsupported_event", False)
    return (
        ok,
        f"text-only model: images sent={sent} vision_unsupported event={row.get('vision_unsupported_event')}",
    )


def diagrams_persisted(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    saved = (row.get("db") or {}).get("diagrams", [])
    if arm.inputs not in ("full", "diagrams_only"):
        return True, "no diagram input"
    expected = [d.stem for d in DIAGRAMS]
    names = [name for name, _ in saved]
    return names == expected, f"saved={names} expected={expected}"


def _sarif_ok(path: Path) -> tuple[bool, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != "2.1.0":
        return False, f"version {data.get('version')}"
    results = [r for run in data.get("runs", []) for r in run.get("results", [])]
    if not results:
        return False, "no results"
    bad = [
        r.get("ruleId")
        for r in results
        if not (r.get("locations") and "physicalLocation" in r["locations"][0])
    ]
    return not bad, f"{len(results)} results; locations[0] not physical: {len(bad)}"


def _pdf_ok(path: Path) -> tuple[bool, str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "".join((page.extract_text() or "") for page in reader.pages[:3])
    return len(reader.pages) > 0 and len(
        text
    ) > 200, f"{len(reader.pages)} pages, {len(text)} chars on pages 1-3"


def exports_valid(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    exports = row.get("exports", {})
    details, ok = [], True
    for fmt in arm.exports:
        name = exports.get(fmt)
        if not name or str(name).startswith("ERROR"):
            ok = False
            details.append(f"{fmt}: {name or 'missing'}")
            continue
        path = run_dir / name
        try:
            if fmt == "sarif":
                good, why = _sarif_ok(path)
            elif fmt == "pdf":
                good, why = _pdf_ok(path)
            elif fmt == "markdown":
                text = path.read_text(encoding="utf-8")
                want = ["ATT&CK"] + (["CVSS"] if arm.scoring in ("cvss", "both") else [])
                missing = [w for w in want if w not in text]
                good, why = not missing, f"missing {missing}" if missing else "ok"
            else:
                json.loads(path.read_text(encoding="utf-8"))
                good, why = True, "ok"
        except (OSError, ValueError, KeyError) as exc:
            good, why = False, f"{type(exc).__name__}: {exc}"
        ok &= good
        details.append(f"{fmt}: {why}")
    return ok, "; ".join(details)


def cvss_consistent(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    cvss = (row.get("db") or {}).get("cvss", {})
    if arm.scoring == "dread":
        return True, "dread-only run"
    ok = (
        cvss.get("with_vector", 0) > 0
        and cvss.get("valid") == cvss.get("with_vector")
        and cvss.get("mismatches") == 0
    )
    return ok, f"{cvss}"


def enrich_complete(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    enrich = row.get("enrich")
    threats = (row.get("db") or {}).get("threats", 0)
    ok = (
        bool(enrich)
        and threats > 0
        and enrich["attack_trees"] == threats
        and enrich["test_suites"] == threats
    )
    return ok, f"enrich={enrich} threats={threats}"


def maestro_present(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    db = row.get("db") or {}
    ok = db.get("maestro", 0) > 0 and sum(db.get("stride", {}).values()) > 0
    return ok, f"maestro={db.get('maestro', 0)} stride={db.get('stride', {})}"


def code_context_used(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    steps = {s["step"] for s in (row.get("usage") or {}).get("steps", [])}
    return "summarize_code" in steps, f"steps={sorted(steps)}"


def _semgrep_processes() -> int:
    if platform.system() == "Windows":
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq semgrep*"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return sum(1 for line in out.splitlines() if line.lower().startswith("semgrep"))
    out = subprocess.run(
        ["pgrep", "-fc", "semgrep"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return int(out or 0)


def no_orphan_semgrep(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    count = _semgrep_processes()
    return count == 0, f"semgrep processes after run: {count}"


def web_contract(row: dict, arm: Arm, run_dir: Path) -> tuple[bool, str]:
    checks = row.get("web_checks") or {}
    failed = {k: v for k, v in checks.items() if v is not True}
    return bool(checks) and not failed, f"failed={failed}" if failed else f"{len(checks)} checks ok"


GATES: dict[str, Gate] = {
    g.__name__: g
    for g in [
        completed,
        no_rule_engine_fallback,
        rule_engine_fallback_reported,
        sources_present,
        images_match_capability,
        diagrams_persisted,
        exports_valid,
        cvss_consistent,
        enrich_complete,
        maestro_present,
        code_context_used,
        no_orphan_semgrep,
        web_contract,
    ]
}


def evaluate(row: dict, arm: Arm, run_dir: Path) -> dict[str, dict]:
    results = {}
    for name in arm.gates:
        try:
            ok, detail = GATES[name](row, arm, run_dir)
        except Exception as exc:  # a crashing gate is a failed gate, with the reason kept
            ok, detail = False, f"gate crashed: {type(exc).__name__}: {exc}"
        results[name] = {"ok": ok, "detail": detail}
    return results
