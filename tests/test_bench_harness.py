"""CI-safe tests for the live benchmark harness (tests/bench/). No network, no credentials."""

import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest

from tests.bench import config as bench_config
from tests.bench.config import ResolvedModel, load_env_file, load_settings, resolve_slot
from tests.bench.estimate import estimate_arm, per_run_estimate
from tests.bench.matrix import DIAGRAMS, FIXTURE, Arm, Suite, build_suites
from tests.bench.prices import Price, PriceTable, run_cost, step_costs, usage_cost
from tests.bench.quality import load_checklist, match_threats, write_spotcheck_sheet
from tests.bench.report import render, spread
from tests.bench.run_one import build_run_args
from tests.bench.runner import BudgetExceededError, RunOutcome, run_suite
from tests.bench.spike import render as render_spike


OPUS = ResolvedModel(
    slot="OPUS_55", provider="bedrock", model_id="opus.id", family="claude", images=True
)
HAIKU = ResolvedModel(
    slot="HAIKU_55", provider="bedrock", model_id="haiku.id", family="claude", images=True
)
OSS = ResolvedModel(
    slot="GPT_OSS_120B", provider="bedrock", model_id="oss.id", family="openai", images=False
)


def _prices(**slots: tuple[float, float]) -> PriceTable:
    return PriceTable(
        models={
            k: Price(
                input=Decimal(str(i)), output=Decimal(str(o)), source="test", read_on="2026-10-09"
            )
            for k, (i, o) in slots.items()
        }
    )


@pytest.fixture
def no_repo_env(monkeypatch, tmp_path):
    """Point the repo root at an empty dir so a developer's real .env can't leak in."""
    monkeypatch.setattr(bench_config, "REPO_ROOT", tmp_path)
    return tmp_path


# --- config -------------------------------------------------------------------


def test_resolve_slot_skips_unset_and_reads_model_id(no_repo_env):
    assert resolve_slot("OPUS_55", {}) is None
    model = resolve_slot("OPUS_55", {"BENCH_MODEL_OPUS_55": " us.anthropic.opus "})
    assert model.model_id == "us.anthropic.opus"
    assert model.provider == "bedrock"
    assert model.images is True


def test_resolve_slot_image_override_and_text_only_default(no_repo_env):
    assert resolve_slot("QWEN", {"BENCH_MODEL_QWEN": "qwen.x"}).images is False
    assert (
        resolve_slot("QWEN", {"BENCH_MODEL_QWEN": "qwen.x", "BENCH_IMAGES_QWEN": "true"}).images
        is True
    )
    assert (
        resolve_slot(
            "OPUS_55", {"BENCH_MODEL_OPUS_55": "o", "BENCH_IMAGES_OPUS_55": "false"}
        ).images
        is False
    )


def test_openai_direct_slot_needs_an_api_key(no_repo_env):
    assert resolve_slot("OPENAI_DIRECT", {}) is None
    model = resolve_slot("OPENAI_DIRECT", {"OPENAI_API_KEY": "sk-test"})
    assert model.model_id == "gpt-4.1"
    assert model.provider == "openai"
    (no_repo_env / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")
    assert resolve_slot("OPENAI_DIRECT", {}) is not None


def test_env_file_is_read_without_touching_os_environ(tmp_path, monkeypatch):
    env_file = tmp_path / "bench.env"
    env_file.write_text("BENCH_MODEL_OPUS_55=from-file\nBENCH_EFFORT=high\n", encoding="utf-8")
    monkeypatch.delenv("BENCH_MODEL_OPUS_55", raising=False)
    assert load_env_file(env_file)["BENCH_MODEL_OPUS_55"] == "from-file"
    assert "BENCH_MODEL_OPUS_55" not in __import__("os").environ
    assert load_env_file(tmp_path / "missing.env") == {}


def test_settings_defaults_and_cap():
    settings = load_settings({})
    assert settings.max_cost_usd is None
    assert settings.effort == "medium"
    assert settings.run_timeout_s == 1800
    assert load_settings({"BENCH_MAX_COST_USD": "12.5"}).max_cost_usd == 12.5


# --- prices -------------------------------------------------------------------


def test_usage_cost_includes_every_token_kind():
    price = Price(
        input=Decimal(2),
        output=Decimal(10),
        cache_read=Decimal("0.2"),
        cache_write=Decimal("2.5"),
        source="t",
        read_on="d",
    )
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
        "cache_read_tokens": 1_000_000,
        "cache_write_tokens": 0,
    }
    assert usage_cost(usage, price) == Decimal("7.2")


def test_run_cost_is_none_when_any_model_is_unpriced():
    prices = _prices(OPUS_55=(4, 20))
    by_model = [
        {"model": "opus.id", "input_tokens": 1_000_000, "output_tokens": 0},
        {"model": "haiku.id", "input_tokens": 10, "output_tokens": 10},
    ]
    assert run_cost(by_model, {"opus.id": "OPUS_55", "haiku.id": "HAIKU_55"}, prices) is None
    assert run_cost(by_model[:1], {"opus.id": "OPUS_55"}, prices) == Decimal(4)
    assert run_cost(by_model, {}, None) is None


def test_step_costs_sum_iterations_and_mark_unpriced_steps():
    prices = _prices(OPUS_55=(1, 1))
    steps = [
        {
            "step": "generate_threats",
            "usage": [{"model": "opus.id", "input_tokens": 1_000_000, "output_tokens": 0}],
        },
        {
            "step": "generate_threats",
            "usage": [{"model": "opus.id", "input_tokens": 1_000_000, "output_tokens": 0}],
        },
        {
            "step": "extract_flows",
            "usage": [{"model": "unknown", "input_tokens": 5, "output_tokens": 5}],
        },
    ]
    out = step_costs(steps, {"opus.id": "OPUS_55"}, prices)
    assert out["generate_threats"] == Decimal(2)
    assert out["extract_flows"] is None


# --- matrix + CLI args ----------------------------------------------------------


def test_build_suites_from_env(no_repo_env):
    env = {
        "BENCH_MODEL_OPUS_55": "opus.id",
        "BENCH_MODEL_HAIKU_55": "haiku.id",
        "BENCH_MODEL_GPT_OSS_120B": "oss.id",
        "BENCH_ROUTING_MAIN": "OPUS_55",
        "BENCH_ROUTING_FAST": "HAIKU_55",
    }
    suites = build_suites(env, load_settings(env))

    assert [a.id for a in suites["e2e-cli"].arms] == [
        "cli-opus_55",
        "cli-haiku_55",
        "cli-gpt_oss_120b",
    ]
    assert any("FABLE_51" in s for s in suites["e2e-cli"].skipped)
    assert any("OPENAI_DIRECT: OPENAI_API_KEY" in s for s in suites["e2e-cli"].skipped)
    assert [a.id for a in suites["e2e-web"].arms] == ["web-opus_55", "web-gpt_oss_120b"]
    assert "text-only-png-gpt_oss_120b" in [a.id for a in suites["e2e-degraded"].arms]
    off, on = suites["bm2-routing"].arms
    assert (off.fast, on.fast.model_id) == (None, "haiku.id")
    assert suites["e2e-code"].arms == []
    assert suites["e2e-code"].skipped == ["BENCH_CODE_REPO not set"]


def test_build_suites_with_nothing_set_has_only_no_llm_arms(no_repo_env):
    suites = build_suites({}, load_settings({}))
    llm_arms = [a for s in suites.values() for a in s.arms if a.main is not None]
    assert llm_arms == []
    assert {a.id for a in suites["e2e-degraded"].arms} == {
        "offline-rule-engine",
        "deadline-partial-deps",
    }


def test_build_run_args_full_input(tmp_path):
    arm = Arm(
        id="x",
        main=OPUS,
        fast=HAIKU,
        step_models={"extract_flows": "main"},
        iterations=3,
        enrich=True,
    )
    args = build_run_args(arm, tmp_path)
    assert args[:2] == ["run", str(FIXTURE / "description.md")]
    assert args[args.index("--manifest") + 1] == str(FIXTURE / "package.json")
    assert args[args.index("--deps-source") + 1] == "both"
    assert [args[i + 1] for i, a in enumerate(args) if a == "-d"] == [str(d) for d in DIAGRAMS]
    assert args[args.index("--model") + 1] == "opus.id"
    assert args[args.index("--fast-model") + 1] == "haiku.id"
    assert args[args.index("--step-model") + 1] == "extract_flows=main"
    assert "--enrich" in args
    assert args[-4:] == ["--format", "full", "-o", str(tmp_path / "out.json")]


def test_build_run_args_variants(tmp_path):
    off = build_run_args(Arm(id="off", main=OPUS, inputs="full_no_diagrams"), tmp_path)
    assert off[off.index("--fast-model") + 1] == "opus.id"  # no routing: fast = main
    assert "-d" not in off
    diagrams = build_run_args(Arm(id="d", main=OPUS, inputs="diagrams_only"), tmp_path)
    assert "--manifest" not in diagrams
    assert diagrams.count("-d") == 3
    offline = build_run_args(Arm(id="o", main=None), tmp_path)
    assert offline[offline.index("--provider") + 1] == "ollama"
    assert "--fast-model" not in offline
    maestro = build_run_args(
        Arm(id="m", main=OPUS, inputs="maestro", stride_maestro=True, code_repo="/r"), tmp_path
    )
    assert "--stride-maestro" in maestro
    assert maestro[maestro.index("--code") + 1] == "/r"


# --- estimate -------------------------------------------------------------------


def test_estimates_unpriced_free_routing_and_web():
    prices = _prices(OPUS_55=(4, 20), HAIKU_55=(0.1, 0.5))
    assert per_run_estimate(Arm(id="a", main=OSS), prices) is None
    assert per_run_estimate(Arm(id="n", main=None), prices) == Decimal(0)
    off = per_run_estimate(Arm(id="off", main=OPUS), prices)
    on = per_run_estimate(Arm(id="on", main=OPUS, fast=HAIKU), prices)
    assert on < off
    cli = estimate_arm(Arm(id="c", main=OPUS), 1, prices)
    web = estimate_arm(Arm(id="w", kind="web", main=OPUS), 1, prices)
    assert web.runs == 3
    assert abs(web.cost - cli.cost * 3) <= Decimal("0.02")


# --- runner -------------------------------------------------------------------


def _write_minimal_db(path: Path, llm_threats: int, total_tokens: int) -> None:
    """Just the tables and columns collect_run reads, with a completed model."""
    usage = json.dumps({"steps": [], "by_model": [], "total_tokens": total_tokens})
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE threat_models (id TEXT, status TEXT, usage_summary TEXT, created_at TEXT);
            CREATE TABLE threats (model_id TEXT, name TEXT, description TEXT, target TEXT, source TEXT,
                stride_category TEXT, maestro_category TEXT, attack_techniques TEXT,
                cvss_vector TEXT, cvss_score REAL, cvss_severity TEXT);
            CREATE TABLE assets (model_id TEXT, name TEXT);
            CREATE TABLE flows (model_id TEXT, source_entity TEXT, target_entity TEXT, flow_description TEXT);
            CREATE TABLE model_diagrams (model_id TEXT, name TEXT, kind TEXT, position INT, created_at TEXT);
            CREATE TABLE dependency_scans (model_id TEXT);
            """
        )
        conn.execute(
            "INSERT INTO threat_models VALUES ('m1', 'completed', ?, '2026-10-10')", (usage,)
        )
        conn.executemany(
            "INSERT INTO threats (model_id, name, source) VALUES ('m1', ?, ?)",
            [(f"llm {i}", "llm") for i in range(llm_threats)] + [("rule", "rule_engine")],
        )


def _fake_executor(
    calls: list, *, llm_threats: int = 3, total_tokens: int = 1000, write_db: bool = True
):
    def run(arm, run_dir, env, timeout_s):
        calls.append((arm.id, run_dir.name, env["DB_PATH"]))
        run_dir.mkdir(parents=True, exist_ok=True)
        if write_db:  # no DB -> no measured cost, so the runner falls back to the estimate
            _write_minimal_db(run_dir / "paranoid.db", llm_threats, total_tokens)
        (run_dir / "run.json").write_text(
            json.dumps({"exit_code": 0, "started": 0, "finished": 1}), encoding="utf-8"
        )
        (run_dir / "out.json").write_text(
            json.dumps({"execution": {"status": "completed"}, "events": []}), encoding="utf-8"
        )
        return RunOutcome(exit_code=0, timed_out=False, seconds=1.0)

    return run


def _suite(*arms: Arm, reps: int = 2) -> Suite:
    return Suite(id="t", title="t", reps=reps, arms=list(arms))


def test_runner_resumes_and_keeps_db_per_run(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    prices = _prices(OPUS_55=(4, 20))
    calls: list = []
    suite = _suite(Arm(id="a", main=OPUS))
    rows = run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor(calls),
        log=lambda _: None,
    )
    assert [r["outcome"] for r in rows] == ["ok", "ok"]
    assert len({c[2] for c in calls}) == 2  # a scratch DB per run
    again = run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor(calls),
        log=lambda _: None,
    )
    assert again == []
    assert len(calls) == 2


def test_runner_stops_before_crossing_the_cap(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    prices = _prices(OPUS_55=(4, 20))
    one_run = per_run_estimate(Arm(id="a", main=OPUS), prices)
    calls: list = []
    with pytest.raises(BudgetExceededError, match="exceed the cap"):
        run_suite(
            _suite(Arm(id="a", main=OPUS), reps=3),
            settings,
            {},
            prices,
            max_cost=one_run * 2 + Decimal("0.001"),
            executor=_fake_executor(calls, write_db=False),
            log=lambda _: None,
        )
    assert len(calls) == 2


def test_runner_refuses_unpriced_models_unless_allowed(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    calls: list = []
    with pytest.raises(BudgetExceededError, match="no price"):
        run_suite(
            _suite(Arm(id="a", main=OSS), reps=1),
            settings,
            {},
            None,
            max_cost=Decimal(100),
            executor=_fake_executor(calls),
            log=lambda _: None,
        )
    assert calls == []
    run_suite(
        _suite(Arm(id="a", main=OSS), reps=1),
        settings,
        {},
        None,
        max_cost=Decimal(100),
        allow_unpriced=True,
        executor=_fake_executor(calls),
        log=lambda _: None,
    )
    assert len(calls) == 1


def test_runner_records_only_allow_listed_settings(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    rows = run_suite(
        _suite(Arm(id="n", main=None), reps=1),
        settings,
        {"AWS_SECRET_ACCESS_KEY": "secret", "AWS_REGION": "us-east-1", "OPENAI_API_KEY": "sk"},
        None,
        max_cost=Decimal(1),
        executor=_fake_executor([]),
        log=lambda _: None,
    )
    recorded = json.dumps(rows[0]["settings"])
    assert "secret" not in recorded
    assert "sk" not in recorded
    assert "us-east-1" in recorded


def test_runner_fails_and_retries_a_run_that_fell_back_to_the_rule_engine(tmp_path):
    """10-09: expired credentials gave 17 rule-engine-only runs recorded as ok and
    skipped on resume. A run whose LLM produced nothing must fail and be retried."""
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    prices = _prices(OPUS_55=(4, 20))
    suite = _suite(Arm(id="a", main=OPUS), reps=1)
    calls: list = []
    first = run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor(calls, llm_threats=0, total_tokens=0),
        log=lambda _: None,
    )
    assert first[0]["outcome"] == "failed"
    assert not first[0]["gates"]["llm_produced_output"]["ok"]
    second = run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor(calls),
        log=lambda _: None,
    )
    assert second[0]["outcome"] == "ok"
    assert len(calls) == 2


def test_retry_archives_the_previous_attempt(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    prices = _prices(OPUS_55=(4, 20))
    suite = _suite(Arm(id="a", main=OPUS), reps=1)
    run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor([], llm_threats=0),
        log=lambda _: None,
    )
    (tmp_path / "t" / "a" / "rep-1" / "calls.jsonl").write_text("stale", encoding="utf-8")
    run_suite(
        suite,
        settings,
        {},
        prices,
        max_cost=Decimal(100),
        executor=_fake_executor([]),
        log=lambda _: None,
    )
    fresh = tmp_path / "t" / "a" / "rep-1"
    archived = tmp_path / "t" / "a" / "rep-1.attempt-1"
    assert (archived / "calls.jsonl").read_text(encoding="utf-8") == "stale"
    assert not (fresh / "calls.jsonl").exists()


def test_no_llm_arms_skip_the_implicit_gate(tmp_path):
    settings = load_settings({"BENCH_OUT_DIR": str(tmp_path)})
    rows = run_suite(
        _suite(Arm(id="n", main=None), reps=1),
        settings,
        {},
        None,
        max_cost=Decimal(1),
        executor=_fake_executor([], llm_threats=0, total_tokens=0),
        log=lambda _: None,
    )
    assert "llm_produced_output" not in rows[0]["gates"]
    assert rows[0]["outcome"] == "ok"


# --- report -------------------------------------------------------------------


def test_spread_formats_median_and_range():
    assert spread([]) == "-"
    assert spread([5]) == "5 (n=1)"
    assert spread([1, 3, 2, None]) == "2 [1-3] (n=3)"


def test_render_has_gates_measurements_and_step_table():
    def row(arm, rep, cost, ok=True):
        return {
            "arm": arm,
            "rep": rep,
            "outcome": "ok" if ok else "failed",
            "wall_s": 100 + rep,
            "cost": cost,
            "gates": {"completed": {"ok": ok, "detail": "why" if not ok else ""}},
            "db": {"threats": 20, "by_source": {"llm": 10, "rule_engine": 9, "dependency": 1}},
            "step_cost": {"extract_flows": cost / 2},
            "usage": {
                "total_tokens": 1000,
                "steps": [{"step": "extract_flows", "duration_ms": 20_000}],
            },
        }

    md = render(
        "bm2-routing",
        [row("off", 1, 1.0), row("off", 2, 1.2), row("on", 1, 0.5), row("on", 2, 0.4, ok=False)],
    )
    assert "| off | 2 | 2 / 0 / 0 | 2/2 |" in md
    assert "| on | 2 | 1 / 1 / 0 | 1/2 |" in md
    assert "1.1 [1-1.2] (n=2)" in md
    assert "| `extract_flows` | 0.5500 | 0.2250 | -59% |" in md
    assert "- `on` rep 2, **completed**: why" in md


# --- quality -------------------------------------------------------------------


def _bag_embed(text: str) -> list[float]:
    vocab = ["ssrf", "webhook", "redis", "queue", "jwt", "secret", "image", "bomb"]
    words = text.lower().replace(".", " ").replace(",", " ").split()
    return [float(sum(w.startswith(v) for w in words)) for v in vocab]


def test_checklist_is_marked_draft_and_well_formed():
    checklist = load_checklist()
    assert checklist["status"].startswith("DRAFT")
    ids = [i["id"] for i in checklist["items"]]
    assert len(ids) == len(set(ids)) == 18
    assert any("deployment.png (only)" in i["from"] for i in checklist["items"])
    assert any("upload-flow.mmd (only)" in i["from"] for i in checklist["items"])


def test_match_threats_uses_threshold():
    checklist = {
        "match": {"threshold": 0.9},
        "items": [
            {"id": "A", "title": "SSRF via webhook", "description": "webhook ssrf"},
            {"id": "B", "title": "Redis queue tampering", "description": "redis queue"},
        ],
    }
    threats = [("Webhook SSRF to internal hosts", "ssrf through the webhook url")]
    result = {m.item_id: m for m in match_threats(threats, checklist, _bag_embed)}
    assert result["A"].matched
    assert result["A"].best_threat == "Webhook SSRF to internal hosts"
    assert not result["B"].matched
    assert (
        match_threats(threats, checklist, _bag_embed, threshold=0.0)[1].matched is False
    )  # zero similarity


def test_spotcheck_sheet_is_blinded(tmp_path):
    run_dir = tmp_path / "suite" / "arm-x" / "rep-1"
    run_dir.mkdir(parents=True)
    with closing(sqlite3.connect(run_dir / "paranoid.db")) as conn, conn:
        conn.execute("CREATE TABLE threat_models (id TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE threats (model_id TEXT, name TEXT, description TEXT)")
        conn.execute("INSERT INTO threat_models VALUES ('m1', '2026-10-09')")
        conn.executemany(
            "INSERT INTO threats VALUES ('m1', ?, ?)", [(f"t{i}", "d") for i in range(5)]
        )
    out = write_spotcheck_sheet([run_dir], tmp_path / "sheet.csv", per_run=3)
    text = out.read_text(encoding="utf-8")
    assert "arm-x" not in text
    assert text.count("R01") == 3
    assert "arm-x" in (tmp_path / "sheet.key.json").read_text(encoding="utf-8")


# --- spike report -----------------------------------------------------------------


def test_spike_render_shows_verbatim_errors():
    results = {
        "models": {
            "OPUS_55": {
                "model_id": "opus.id",
                "converse": {
                    "text": {"ok": True, "stop_reason": "end_turn"},
                    "forced_tool": {
                        "ok": False,
                        "error": 'ValidationException: tool_choice: type "tool" not supported',
                    },
                },
                "provider": {"structured_probe": {"ok": True}},
            }
        }
    }
    md = render_spike(results)
    assert "| OPUS_55 | `opus.id` | ok (end_turn) |" in md
    assert 'tool_choice: type "tool" not supported' in md


def test_fixture_inputs_exist():
    for path in [
        FIXTURE / "description.md",
        FIXTURE / "package.json",
        FIXTURE / "package-lock.json",
        *DIAGRAMS,
    ]:
        assert Path(path).is_file(), path
