"""Suites and arms: what each run is (model, inputs, flags) and which gates apply.

The registry is built from the environment, so a model slot without an ID simply
yields no arm (reported by `list`/`plan` as skipped) instead of failing.
"""

from typing import Literal

from pydantic import BaseModel, Field

from tests.bench.config import REPO_ROOT, SLOTS, BenchSettings, ResolvedModel, resolve_slot


FIXTURE = REPO_ROOT / "examples" / "arsenal-deps"
DIAGRAMS = [
    FIXTURE / "diagrams" / "architecture.mmd",
    FIXTURE / "diagrams" / "upload-flow.mmd",
    FIXTURE / "diagrams" / "deployment.png",
]
MAESTRO_DESCRIPTION = REPO_ROOT / "examples" / "maestro-example-rag-chatbot.md"
MAESTRO_DIAGRAM = REPO_ROOT / "examples" / "maestro-rag-chatbot-architecture.mmd"

# Terms that appear in exactly one input diagram (examples/arsenal-deps/README.md).
PROBE_TERMS = {
    "secrets_manager": r"secrets?[ -]manager",
    "dead_letter_queue": r"dead[ -]letter|\bDLQ\b",
}

Inputs = Literal["full", "full_no_diagrams", "diagrams_only", "maestro"]
ALL_EXPORTS = ("simple", "sarif", "markdown", "pdf")


class Arm(BaseModel):
    id: str
    kind: Literal["cli", "web"] = "cli"
    main: ResolvedModel | None  # None: no LLM (degraded/offline arms)
    fast: ResolvedModel | None = None  # None: same model as main (no routing)
    step_models: dict[str, Literal["fast", "main"]] = Field(default_factory=dict)
    inputs: Inputs = "full"
    iterations: int = 2
    enrich: bool = False
    scoring: Literal["dread", "cvss", "both"] = "both"
    deps_source: Literal["npm", "both"] = "both"
    code_repo: str | None = None
    stride_maestro: bool = False
    exports: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    gates: tuple[str, ...] = ()
    timeout_factor: float = 1.0

    @property
    def pipeline_runs_per_rep(self) -> int:
        return 3 if self.kind == "web" else 1

    @property
    def images_sent(self) -> bool:
        return bool(self.main and self.main.images and self.inputs in ("full", "diagrams_only"))


class Suite(BaseModel):
    id: str
    title: str
    reps: int
    arms: list[Arm]
    skipped: list[str] = Field(default_factory=list)  # why an intended arm isn't here
    notes: str = ""


CLI_GATES = (
    "completed",
    "no_rule_engine_fallback",
    "sources_present",
    "images_match_capability",
    "diagrams_persisted",
    "exports_valid",
    "cvss_consistent",
    "no_orphan_semgrep",
)


def _resolve(names: list[str], env: dict[str, str], skipped: list[str]) -> list[ResolvedModel]:
    out = []
    for name in names:
        model = resolve_slot(name, env)
        if model is None:
            need = "OPENAI_API_KEY" if SLOTS[name].provider == "openai" else SLOTS[name].env_var
            skipped.append(f"{name}: {need} not set")
        else:
            out.append(model)
    return out


def _all_models(env: dict[str, str], skipped: list[str]) -> list[ResolvedModel]:
    return _resolve(list(SLOTS), env, skipped)


def _first_non_claude(models: list[ResolvedModel]) -> ResolvedModel | None:
    return next((m for m in models if m.family != "claude"), None)


def build_suites(env: dict[str, str], settings: BenchSettings) -> dict[str, Suite]:
    suites: list[Suite] = []

    # --- E2E (functional gates) --------------------------------------------
    sk: list[str] = []
    models = _all_models(env, sk)
    suites.append(
        Suite(
            id="e2e-cli",
            title="E2E-1: CLI, full input, every export format",
            reps=1,
            skipped=sk,
            arms=[
                Arm(id=f"cli-{m.slot.lower()}", main=m, exports=ALL_EXPORTS, gates=CLI_GATES)
                for m in models
            ],
        )
    )

    sk = []
    web_models = list(_resolve(["OPUS_55"], env, sk))
    other = _first_non_claude(_all_models(env, []))
    if other:
        web_models.append(other)
    else:
        sk.append("non-Claude web arm: no non-Claude slot set")
    suites.append(
        Suite(
            id="e2e-web",
            title="E2E-2/3: web/API path, SSE, diagram reuse and replace",
            reps=1,
            skipped=sk,
            arms=[
                Arm(
                    id=f"web-{m.slot.lower()}",
                    kind="web",
                    main=m,
                    exports=ALL_EXPORTS,
                    iterations=1,
                    gates=("completed", "web_contract", "exports_valid", "cvss_consistent"),
                    timeout_factor=3.0,
                )
                for m in web_models
            ],
            notes="Each web arm makes 3 pipeline runs (first run, re-run with no upload, re-run with 1 diagram).",
        )
    )

    sk = []
    enrich_models = _resolve(["OPUS_55", "HAIKU_55"], env, sk)
    if other:
        enrich_models.append(other)
    suites.append(
        Suite(
            id="e2e-enrich",
            title="E2E-4 / EN-1: --enrich (attack trees + test cases)",
            reps=1,
            skipped=sk,
            arms=[
                Arm(
                    id=f"enrich-{m.slot.lower()}",
                    main=m,
                    enrich=True,
                    iterations=1,
                    exports=("markdown", "pdf"),
                    gates=("completed", "enrich_complete", "exports_valid"),
                    timeout_factor=2.0,
                )
                for m in enrich_models
            ],
        )
    )

    sk = []
    opus = _resolve(["OPUS_55"], env, sk)
    code_arms = []
    if not settings.code_repo:
        sk.append("BENCH_CODE_REPO not set")
    elif opus:
        code_arms.append(
            Arm(
                id="code-opus_55",
                main=opus[0],
                code_repo=str(settings.code_repo),
                iterations=1,
                gates=("completed", "code_context_used"),
            )
        )
    suites.append(
        Suite(
            id="e2e-code",
            title="E2E-5: code as input (context-link)",
            reps=1,
            skipped=sk,
            arms=code_arms,
        )
    )

    suites.append(
        Suite(
            id="e2e-maestro",
            title="E2E-6: MAESTRO + STRIDE on an AI-system description",
            reps=1,
            skipped=[] if opus else ["OPUS_55: BENCH_MODEL_OPUS_55 not set"],
            arms=[
                Arm(
                    id="maestro-opus_55",
                    main=m,
                    inputs="maestro",
                    iterations=1,
                    stride_maestro=True,
                    gates=("completed", "maestro_present"),
                )
                for m in opus
            ],
        )
    )

    sk = []
    degraded = [
        Arm(
            id="offline-rule-engine",
            main=None,
            iterations=1,
            env={"OLLAMA_BASE_URL": "http://127.0.0.1:1"},
            gates=("completed", "rule_engine_fallback_reported"),
        ),
        Arm(
            id="deadline-partial-deps",
            main=None,
            iterations=1,
            deps_source="both",
            env={"OLLAMA_BASE_URL": "http://127.0.0.1:1", "DEPS_ANALYSIS_TIMEOUT_SECONDS": "20"},
            gates=("completed", "no_orphan_semgrep"),
        ),
    ]
    text_only = next((m for m in _all_models(env, []) if not m.images), None)
    if text_only:
        degraded.append(
            Arm(
                id=f"text-only-png-{text_only.slot.lower()}",
                main=text_only,
                iterations=1,
                gates=("completed", "no_rule_engine_fallback", "images_match_capability"),
            )
        )
    else:
        sk.append("text-only + PNG arm: no text-only slot set")
    suites.append(
        Suite(id="e2e-degraded", title="E2E-7: degraded modes", reps=1, skipped=sk, arms=degraded)
    )

    # --- Model comparison ----------------------------------------------------
    sk = []
    suites.append(
        Suite(
            id="mc",
            title="MC: model comparison (each model as both main and fast)",
            reps=3,
            skipped=sk,
            arms=[Arm(id=f"mc-{m.slot.lower()}", main=m) for m in _all_models(env, sk)],
            notes="Quality is scored separately (`report mc --quality`) against the reviewed MediaDrop checklist.",
        )
    )

    # --- Benchmarks ------------------------------------------------------------
    sk = []
    main_slot, fast_slot = settings.routing_main, settings.routing_fast
    rmain = _resolve([main_slot], env, sk) if main_slot in SLOTS else []
    rfast = _resolve([fast_slot], env, sk) if fast_slot in SLOTS else []
    if not (main_slot in SLOTS and fast_slot in SLOTS):
        sk.append("BENCH_ROUTING_MAIN / BENCH_ROUTING_FAST must name model slots")
    routing_ok = bool(rmain and rfast)

    def _routing_arms(prefix: str, **kw) -> list[Arm]:
        if not routing_ok:
            return []
        return [
            Arm(id=f"{prefix}-off", main=rmain[0], fast=None, **kw),
            Arm(id=f"{prefix}-on", main=rmain[0], fast=rfast[0], **kw),
        ]

    suites.append(
        Suite(
            id="bm2-routing",
            title="BM2: routing on/off (4a-3 protocol)",
            reps=3,
            skipped=list(sk),
            arms=_routing_arms("bm2", inputs="full_no_diagrams", iterations=3, deps_source="npm"),
        )
    )
    suites.append(
        Suite(
            id="bm3-enrich-routing",
            title="BM3 / EN-2: routing on/off with --enrich",
            reps=2,
            skipped=list(sk),
            arms=_routing_arms(
                "bm3",
                inputs="full_no_diagrams",
                iterations=2,
                deps_source="npm",
                enrich=True,
                timeout_factor=2.5,
            ),
        )
    )
    bm4 = []
    if routing_ok:
        bm4 = [
            Arm(
                id="bm4-fast-extraction",
                main=rmain[0],
                fast=rfast[0],
                inputs="diagrams_only",
                iterations=1,
            ),
            Arm(
                id="bm4-main-extraction",
                main=rmain[0],
                fast=rfast[0],
                inputs="diagrams_only",
                iterations=1,
                step_models={"extract_assets": "main", "extract_flows": "main"},
            ),
        ]
    suites.append(
        Suite(
            id="bm4-diagrams",
            title="BM4: image-only components vs extraction model",
            reps=3,
            skipped=list(sk),
            arms=bm4,
        )
    )
    suites.append(
        Suite(
            id="bm5-iterations",
            title="BM5: value of each iteration",
            reps=3,
            skipped=list(sk),
            arms=[
                Arm(
                    id="bm5-n5",
                    main=rmain[0],
                    inputs="full_no_diagrams",
                    iterations=5,
                    deps_source="npm",
                    env={"MIN_ITERATIONS": "5"},
                    timeout_factor=1.5,
                )
            ]
            if rmain
            else [],
        )
    )

    sk = []
    demo_main = _resolve(["OPUS_55"], env, sk)
    demo = []
    if demo_main:
        m = demo_main[0]
        f = rfast[0] if rfast else None
        demo = [
            Arm(
                id="demo-s1-deps",
                main=m,
                fast=f,
                inputs="full_no_diagrams",
                iterations=2,
                deps_source="both",
            ),
            Arm(
                id="demo-s2-diagrams",
                main=m,
                fast=f,
                inputs="full",
                iterations=2,
                step_models={"extract_assets": "main", "extract_flows": "main"},
            ),
            Arm(
                id="demo-s3-routing",
                main=m,
                fast=f,
                inputs="full_no_diagrams",
                iterations=2,
                deps_source="npm",
                exports=("sarif",),
            ),
        ]
    suites.append(
        Suite(
            id="bm10-demo",
            title="BM10: demo commands, wall time p50/p90",
            reps=5,
            skipped=sk,
            arms=demo,
        )
    )

    sk = []
    flagship = _resolve(["OPUS_55", "FABLE_51"], env, sk)
    if not settings.code_repo:
        sk.append("BENCH_CODE_REPO not set: flagship runs without code input")
    suites.append(
        Suite(
            id="bm13-flagship",
            title="BM13: flagship full-input sessions",
            reps=1,
            skipped=sk,
            arms=[
                Arm(
                    id=f"flagship-{m.slot.lower()}",
                    main=m,
                    enrich=True,
                    iterations=3,
                    code_repo=str(settings.code_repo) if settings.code_repo else None,
                    exports=ALL_EXPORTS,
                    timeout_factor=3.0,
                )
                for m in flagship
            ],
        )
    )

    return {s.id: s for s in suites}


# Deterministic suites that already exist as pytest/live tests (no LLM spend).
EXTERNAL_SUITES = {
    "bm7-attack-golden": "pytest -m live tests/live/test_attack_mapping_golden.py -v",
    "bm9-deps-benchmark": "pytest -m live tests/live/test_deps_benchmark.py -v   (run on Windows and Linux at the same time)",
    "bm1-malware-recall": "pending: needs BENCH_MALWARE_DIR samples and the scanner adapter (Phase 2)",
    "bm15-install": "manual: docker compose up --build on a clean machine (time, image size, cold start)",
}
