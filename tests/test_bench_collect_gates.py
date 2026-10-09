"""CI-safe tests for the harness's metric collection and E2E gates, on a real (migrated) fixture DB."""

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from backend.db import crud
from tests.bench import gates as bench_gates
from tests.bench.collect import collect_run
from tests.bench.config import ResolvedModel
from tests.bench.gates import evaluate
from tests.bench.matrix import CLI_GATES, DIAGRAMS, Arm
from tests.bench.prices import Price, PriceTable


OPUS = ResolvedModel(
    slot="OPUS_55", provider="bedrock", model_id="opus.id", family="claude", images=True
)
OSS = ResolvedModel(
    slot="GPT_OSS_120B", provider="bedrock", model_id="oss.id", family="openai", images=False
)
PRICES = PriceTable(
    models={"OPUS_55": Price(input=Decimal(4), output=Decimal(20), source="t", read_on="d")}
)
VALID_VECTOR = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"  # 9.8 critical

USAGE = {
    "steps": [
        {
            "step": "extract_flows",
            "iteration": 0,
            "status": "completed",
            "provider": "bedrock",
            "model": "opus.id",
            "duration_ms": 20_000,
            "input_hash": "",
            "output_hash": "",
            "usage": [
                {
                    "provider": "bedrock",
                    "model": "opus.id",
                    "calls": 1,
                    "input_tokens": 1_000_000,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "total_tokens": 1_000_000,
                }
            ],
        },
    ],
    "by_model": [
        {
            "provider": "bedrock",
            "model": "opus.id",
            "calls": 1,
            "input_tokens": 1_000_000,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "total_tokens": 1_000_000,
        }
    ],
    "total_tokens": 1_000_000,
    "fast_routing_disabled": False,
}


async def _populate(*, dependency_threats: int = 7, bad_cvss: bool = False) -> str:
    mid = await crud.create_threat_model(
        title="t", description="d" * 20, provider="bedrock", model="opus.id", scoring_method="both"
    )
    for i in range(3):
        await crud.create_threat(
            model_id=mid,
            name=f"LLM threat {i}",
            description="via the secrets manager",
            target="API",
            impact="h",
            likelihood="m",
            mitigations=["x"],
            stride_category="Spoofing",
            source="llm",
            cvss_vector=VALID_VECTOR,
            cvss_score=5.0 if (bad_cvss and i == 0) else 9.8,
            cvss_severity="critical",
            attack_techniques=[{"id": "T1190"}],
        )
    await crud.create_threat(
        model_id=mid,
        name="Rule threat",
        description="r",
        target="Redis",
        impact="h",
        likelihood="m",
        mitigations=[],
        stride_category="Tampering",
        source="rule_engine",
    )
    for i in range(dependency_threats):
        await crud.create_threat(
            model_id=mid,
            name=f"Dep {i}",
            description="dep",
            target="pkg",
            impact="m",
            likelihood="m",
            mitigations=[],
            stride_category="Tampering",
            source="dependency",
        )
    await crud.create_asset(mid, "Datastore", "Secrets Manager", "keys")
    await crud.create_flow(
        mid, "data", "moves failed jobs to the dead-letter queue", "Worker", "Redis"
    )
    for diagram in DIAGRAMS:
        await crud.create_model_diagram(
            model_id=mid,
            name=diagram.stem,
            kind="png" if diagram.suffix == ".png" else "mermaid",
            content="x",
            size_bytes=1,
            media_type="image/png" if diagram.suffix == ".png" else None,
        )
    await crud.update_threat_model(mid, usage_summary=json.dumps(USAGE))
    await crud.update_threat_model_status(mid, "completed")
    return mid


def _run_dir(
    tmp_path: Path, db_path: str, *, calls: list[dict], log: str = "", events: list | None = None
) -> Path:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    shutil.copy(db_path, run_dir / "paranoid.db")
    (run_dir / "run.json").write_text(
        json.dumps({"exit_code": 0, "started": 0, "finished": 12.5, "exports": {}}),
        encoding="utf-8",
    )
    (run_dir / "out.json").write_text(
        json.dumps(
            {
                "execution": {
                    "status": "completed",
                    "iterations_completed": 2,
                    "duration_seconds": 10,
                    "stopped_reason": "max_iterations",
                },
                "events": events or [],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "calls.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8"
    )
    (run_dir / "stdout.log").write_text(log, encoding="utf-8")
    return run_dir


def _image_calls(n: int) -> list[dict]:
    return [
        {"response_model": rm, "images": n, "diagram_tags": [' name="a"', ' name="b"', ' name="c"']}
        for rm in ("SummaryState", "AssetsList", "FlowsList")
    ]


@pytest.fixture(autouse=True)
def no_semgrep(monkeypatch):
    monkeypatch.setattr(bench_gates, "_semgrep_processes", lambda: 0)


async def test_collect_reads_db_logs_calls_and_prices(test_db, tmp_path):
    await _populate()
    log = (
        "Anthropic response failed JSON parsing (x)\nOutput truncated, auto-bumping to 8192\n"
        "Enrichment complete: 11 attack trees, 11 test suites\n"
    )
    run_dir = _run_dir(tmp_path, test_db, calls=_image_calls(1), log=log)
    row = collect_run(run_dir, Arm(id="a", main=OPUS), PRICES)

    assert row["wall_s"] == 12.5
    assert row["iterations"] == 2
    assert row["db"]["by_source"] == {"llm": 3, "rule_engine": 1, "dependency": 7}
    assert row["db"]["diagrams"] == [
        (d.stem, "png" if d.suffix == ".png" else "mermaid") for d in DIAGRAMS
    ]
    assert row["db"]["cvss"] == {
        "with_vector": 3,
        "valid": 3,
        "mismatches": 0,
        "distinct_vectors": 1,
    }
    assert row["db"]["with_attack_techniques"] == 3
    assert row["db"]["probe_hits"]["secrets_manager"] == {"assets": 1, "flows": 0, "threats": 3}
    assert row["db"]["probe_hits"]["dead_letter_queue"]["flows"] == 1
    assert row["reliability"]["json_retries"] == 1
    assert row["reliability"]["auto_bumps"] == 1
    assert row["enrich"] == {"attack_trees": 11, "test_suites": 11}
    assert row["cost"] == 4.0
    assert row["step_cost"] == {"extract_flows": 4.0}
    assert row["calls"]["images_by_response_model"] == {
        "SummaryState": 1,
        "AssetsList": 1,
        "FlowsList": 1,
    }


async def test_cli_gates_pass_on_a_good_run(test_db, tmp_path):
    await _populate()
    run_dir = _run_dir(tmp_path, test_db, calls=_image_calls(1))
    arm = Arm(id="a", main=OPUS, gates=tuple(g for g in CLI_GATES if g != "exports_valid"))
    results = evaluate(collect_run(run_dir, arm, PRICES), arm, run_dir)
    assert all(r["ok"] for r in results.values()), results


async def test_gates_catch_wrong_dependency_count_and_cvss_mismatch(test_db, tmp_path):
    await _populate(dependency_threats=6, bad_cvss=True)
    run_dir = _run_dir(tmp_path, test_db, calls=_image_calls(1))
    arm = Arm(id="a", main=OPUS, gates=("sources_present", "cvss_consistent"))
    results = evaluate(collect_run(run_dir, arm, PRICES), arm, run_dir)
    assert not results["sources_present"]["ok"]
    assert "6 != 7" in results["sources_present"]["detail"]
    assert not results["cvss_consistent"]["ok"]


async def test_image_gate_text_only_model_needs_skip_event_and_no_images(test_db, tmp_path):
    await _populate()
    arm = Arm(id="a", main=OSS, gates=("images_match_capability",))
    skipped_event = [
        {
            "step": "summarize",
            "status": "info",
            "message": "The Ollama provider doesn't send images; 1 image diagram(s) skipped, Mermaid diagrams are used.",
        }
    ]
    ok_dir = _run_dir(tmp_path / "ok", test_db, calls=_image_calls(0), events=skipped_event)
    assert evaluate(collect_run(ok_dir, arm, None), arm, ok_dir)["images_match_capability"]["ok"]
    bad_dir = _run_dir(tmp_path / "bad", test_db, calls=_image_calls(1), events=skipped_event)
    assert not evaluate(collect_run(bad_dir, arm, None), arm, bad_dir)["images_match_capability"][
        "ok"
    ]


async def test_image_gate_capable_model_needs_one_image_per_extraction_call(test_db, tmp_path):
    await _populate()
    arm = Arm(id="a", main=OPUS, gates=("images_match_capability",))
    missing = _image_calls(1)[:2]  # FlowsList had no image
    run_dir = _run_dir(tmp_path, test_db, calls=missing)
    result = evaluate(collect_run(run_dir, arm, PRICES), arm, run_dir)["images_match_capability"]
    assert not result["ok"]
    assert "FlowsList" in result["detail"]


def test_sarif_gate_requires_physical_first_location(tmp_path):
    arm = Arm(id="a", main=OPUS, exports=("sarif",), gates=("exports_valid",))
    good = {
        "version": "2.1.0",
        "runs": [
            {
                "results": [
                    {
                        "ruleId": "r",
                        "locations": [
                            {
                                "physicalLocation": {"artifactLocation": {"uri": "package.json"}},
                                "logicalLocations": [{"name": "npm:x@1"}],
                            }
                        ],
                    }
                ]
            }
        ],
    }
    bad = {
        "version": "2.1.0",
        "runs": [
            {
                "results": [
                    {
                        "ruleId": "r",
                        "locations": [
                            {"logicalLocations": [{"name": "npm:x@1"}]},
                            {"physicalLocation": {}},
                        ],
                    }
                ]
            }
        ],
    }
    for name, doc, expected in (("good", good, True), ("bad", bad, False)):
        d = tmp_path / name
        d.mkdir()
        (d / "export-sarif.sarif").write_text(json.dumps(doc), encoding="utf-8")
        row = {"exports": {"sarif": "export-sarif.sarif"}}
        assert evaluate(row, arm, d)["exports_valid"]["ok"] is expected


def test_export_error_and_missing_exports_fail(tmp_path):
    arm = Arm(id="a", main=OPUS, exports=("pdf", "markdown"), gates=("exports_valid",))
    row = {"exports": {"pdf": "ERROR SystemExit: 1"}}
    result = evaluate(row, arm, tmp_path)["exports_valid"]
    assert not result["ok"]
    assert "markdown: missing" in result["detail"]


def test_enrich_and_crashing_gates():
    arm = Arm(id="a", main=OPUS, gates=("enrich_complete", "web_contract"))
    row = {
        "enrich": {"attack_trees": 5, "test_suites": 4},
        "db": {"threats": 5},
        "web_checks": {"sse_complete": True, "x": False},
    }
    results = evaluate(row, arm, Path())
    assert not results["enrich_complete"]["ok"]
    assert not results["web_contract"]["ok"]
    assert "'x': False" in results["web_contract"]["detail"]
    crash = evaluate({"db": None}, Arm(id="b", main=OPUS, gates=("maestro_present",)), Path())
    assert crash["maestro_present"]["ok"] is False


def test_collect_without_a_db_still_returns_a_row(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    (run_dir / "run.json").write_text(
        json.dumps({"exit_code": 1, "error": "boom", "started": 0, "finished": 1}), encoding="utf-8"
    )
    row = collect_run(run_dir, Arm(id="a", main=OPUS), PRICES)
    assert row["db"] is None
    assert row["error"] == "boom"
    assert not evaluate(row, Arm(id="a", main=OPUS, gates=("completed",)), run_dir)["completed"][
        "ok"
    ]
