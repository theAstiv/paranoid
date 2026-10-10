"""Pipeline orchestrator with iteration logic and SSE event streaming.

The runner coordinates all pipeline nodes, manages the iteration loop,
and emits server-sent events for real-time progress tracking.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal, get_args

from pydantic import BaseModel

from backend.config import settings
from backend.dedup import deduplicate_threats
from backend.deps.analyze import analyze_manifest
from backend.deps.threats import dependency_threats, merge_dependency_threats
from backend.image.errors import DiagramValidationError
from backend.image.validation import validate_diagram_set
from backend.models.dependencies import DependencyContext
from backend.models.enums import DiagramFormat, Framework, ScoringMethod, StrideCategory
from backend.models.extended import AttackTree, CodeContext, DiagramData, TestSuite
from backend.models.state import AssetsList, FlowsList, SummaryState, ThreatsList
from backend.models.usage import StepRun
from backend.pipeline import nodes
from backend.pipeline.nodes.helpers import build_shared_context
from backend.providers.base import (
    LLMProvider,
    ProviderError,
    ProviderRefusalError,
    ProviderTransientError,
)
from backend.providers.usage import build_run_usage, collect_usage, summarize_usage
from backend.rules.engine import fetch_rag_context, merge_rule_and_llm_threats, run_rule_engine
from backend.serialization import serialize_event_data


logger = logging.getLogger(__name__)

StopAfter = Literal["extraction"]

# Grace period added on top of `deps_analysis_timeout_seconds` for the outer
# dependency-analysis backstop (see below). analyze_manifest() budgets each
# package against a deadline equal to the base timeout and returns whatever
# finished once it passes — but cancelling a still-running Semgrep scan can
# itself take up to ~10s (backend.deps.scanner._kill_process_tree: a taskkill
# call plus two 5s waits). Without this grace, the outer wait_for(timeout=...)
# can fire while analyze_manifest is still finishing that cleanup, discarding
# the whole partial DependencyContext it was about to return — exactly the
# all-or-nothing failure the deadline exists to avoid.
_DEPS_ANALYSIS_BACKSTOP_GRACE_S = 30.0


def _provider_error_event_data(e: ProviderError) -> dict:
    """Build a PipelineEvent `data` dict for a caught ProviderError, flagging
    refusals so the bench harness and the UI can count them separately from
    other provider failures."""
    data: dict = {"error": str(e)}
    if isinstance(e, ProviderRefusalError):
        data["refusal"] = True
    return data


def _hash_value(value: Any) -> str:
    """Stable fingerprint of a step's input or output for the pipeline_runs audit.

    Not meant to byte-reproduce the value — Pydantic models are dumped via
    `model_dump(mode="json")` so the hash only changes when the data does,
    not the containing object's identity.
    """
    if isinstance(value, BaseModel):
        payload: Any = value.model_dump(mode="json")
    elif isinstance(value, list | tuple):
        payload = [v.model_dump(mode="json") if isinstance(v, BaseModel) else v for v in value]
    elif isinstance(value, dict):
        payload = {
            k: (v.model_dump(mode="json") if isinstance(v, BaseModel) else v)
            for k, v in value.items()
        }
    else:
        payload = value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _is_stride_coverage_balanced(threats: ThreatsList, min_per_category: int = 2) -> bool:
    """Return True when all STRIDE categories have at least min_per_category threats.

    Used as a cheap deterministic gate before the LLM gap-analysis call. When every
    category is covered at the minimum level, the gap call (max_tokens=1536) would
    just return stop=True. The gate avoids that round trip.

    Note: MAESTRO threats also carry stride_category and feed the same counter in
    dual-framework runs, so the gate is conservative — it only fires when both
    frameworks have jointly covered all six STRIDE categories.

    Args:
        threats: Cumulative threat catalog from all completed iterations.
        min_per_category: Minimum threats per STRIDE category to consider balanced.

    Returns:
        True if every StrideCategory value appears at least min_per_category times.
    """
    counts = Counter(t.stride_category for t in threats.threats)
    return all(counts.get(cat, 0) >= min_per_category for cat in StrideCategory)


class PipelineStep(str, Enum):
    """Pipeline step identifiers for SSE events."""

    ANALYZE_DEPENDENCIES = "analyze_dependencies"
    SUMMARIZE = "summarize"
    SUMMARIZE_CODE = "summarize_code"
    EXTRACT_ASSETS = "extract_assets"
    EXTRACT_FLOWS = "extract_flows"
    GENERATE_THREATS = "generate_threats"
    GAP_ANALYSIS = "gap_analysis"
    ITERATE = "iterate"
    GENERATE_ATTACK_TREE = "generate_attack_tree"
    GENERATE_TEST_CASES = "generate_test_cases"
    RULE_ENGINE = "rule_engine"
    MAP_TECHNIQUES = "map_techniques"
    COMPLETE = "complete"


StepModelChoice = Literal["fast", "main"]

# generate_threats and gap_analysis are the pipeline's highest-stakes LLM
# calls — never route them to the cheaper fast model, regardless of config.
FORBIDDEN_FAST_STEPS = frozenset({PipelineStep.GENERATE_THREATS, PipelineStep.GAP_ANALYSIS})

# Default per-step routing. Reproduces, exactly, the hardcoded main/fast
# split that predates per-step config, so enabling step_models changes no
# behaviour for existing callers that don't set it.
_DEFAULT_STEP_MODELS: dict[PipelineStep, StepModelChoice] = {
    PipelineStep.SUMMARIZE: "main",
    PipelineStep.SUMMARIZE_CODE: "main",
    PipelineStep.EXTRACT_ASSETS: "fast",
    PipelineStep.EXTRACT_FLOWS: "fast",
    PipelineStep.GENERATE_THREATS: "main",
    PipelineStep.GAP_ANALYSIS: "main",
    PipelineStep.GENERATE_ATTACK_TREE: "fast",
    PipelineStep.GENERATE_TEST_CASES: "fast",
}

# Per-provider overrides applied on top of _DEFAULT_STEP_MODELS. gpt-4.1-mini
# shares gpt-4.1's 32,768-token output ceiling (not a capacity limit), but
# dense MAESTRO flow extraction is suspected to come out thinner on the mini
# model — unmeasured as of week 4a-2, so this provider default stays
# conservative (main) until the 4a-3 routing comparison quantifies it.
_PROVIDER_STEP_MODEL_OVERRIDES: dict[str, dict[PipelineStep, StepModelChoice]] = {
    "openai": {PipelineStep.EXTRACT_FLOWS: "main"},
}


def default_step_models(provider_name: str) -> dict[PipelineStep, StepModelChoice]:
    """Return the default fast/main routing map for a provider name."""
    merged = dict(_DEFAULT_STEP_MODELS)
    merged.update(_PROVIDER_STEP_MODEL_OVERRIDES.get(provider_name, {}))
    return merged


def validate_step_models(step_models: dict[PipelineStep, StepModelChoice]) -> None:
    """Raise ValueError if a forbidden step is routed to the fast model."""
    violations = sorted(s.value for s in FORBIDDEN_FAST_STEPS if step_models.get(s) == "fast")
    if violations:
        raise ValueError(f"Steps {violations} can never be routed to the fast model")


def resolve_step_models(
    provider_name: str,
    overrides: dict[PipelineStep, StepModelChoice] | None,
) -> dict[PipelineStep, StepModelChoice]:
    """Merge an override layer onto the provider's default routing map.

    Must be a merge, not a replace: a step absent from `overrides` keeps its
    provider default rather than silently falling back to "main" — e.g.
    ``{SUMMARIZE: "fast"}`` must not also move extract_assets/extract_flows
    off the fast model they default to.
    """
    merged = default_step_models(provider_name)
    if overrides:
        merged.update(overrides)
        validate_step_models(merged)
    return merged


def step_models_override_from_settings(
    explicit: dict[PipelineStep, StepModelChoice] | None,
    env_step_models: dict[str, str],
) -> dict[PipelineStep, StepModelChoice] | None:
    """Build the override layer passed as ``PipelineConfig.step_models``.

    An explicit override (e.g. a CLI ``--step-model`` flag) takes priority
    entirely over ``settings.step_models`` (the ``STEP_MODELS`` env var);
    when neither is set, returns None so ``resolve_step_models`` applies
    pure provider defaults. Settings.step_models keys are already-validated
    PipelineStep values (validated at Settings() construction) by the time
    this runs, so the enum conversion here cannot raise.
    """
    if explicit is not None:
        return explicit
    if env_step_models:
        return {PipelineStep(name): choice for name, choice in env_step_models.items()}
    return None


@dataclass
class PipelineEvent:
    """SSE event for pipeline progress."""

    step: PipelineStep
    status: str  # "started" | "completed" | "failed" | "info"
    message: str
    iteration: int | None = None
    data: dict | None = None
    timestamp: float | None = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_sse_format(self) -> str:
        """Convert to SSE format string for Server-Sent Events streaming."""
        event_data = {
            "step": self.step.value if isinstance(self.step, PipelineStep) else self.step,
            "status": self.status,
            "message": self.message,
            "iteration": self.iteration,
            "data": serialize_event_data(self.data),
            "timestamp": self.timestamp,
        }
        return f"data: {json.dumps(event_data)}\n\n"


@dataclass
class PipelineConfig:
    """Configuration for pipeline execution."""

    max_iterations: int = 3  # 1-15 allowed
    max_execution_time_minutes: int = 30
    temperature: float = 0.2
    enable_rag: bool = True  # Enable RAG retrieval for threat generation
    has_ai_components: bool = False  # Run MAESTRO alongside STRIDE when True
    similarity_threshold: float = 0.85  # Dedup threshold for embedding cosine similarity
    dedup_saturation_threshold: float = 0.7  # Stop if ≥N fraction of new threats were duplicates
    min_iterations: int = 1  # Min iterations before early-stop conditions (gap/saturation) fire
    seed_collections: list[str] | None = None  # None = all seed collections; [] treated as None
    # Override layer merged onto the provider's default routing map by
    # PipelineRunner (see resolve_step_models) — a step left out here keeps
    # its provider default. None = pure provider defaults, no override.
    step_models: dict[PipelineStep, StepModelChoice] | None = None
    # "dread" (default, no behaviour change) | "cvss" | "both". Drives the
    # dependency-threats default-vector lookup (backend.deps.threats) and
    # whether generate_threats() keeps/scores a provider's `cvss` metrics
    # or force-clears them. The STRIDE/MAESTRO prompts don't yet ask for
    # CVSS metrics (day 2 — the instruction block isn't wired in), so a
    # provider has to volunteer `cvss` unprompted for "cvss"/"both" to have
    # any effect on LLM-sourced threats today.
    scoring_method: ScoringMethod = "dread"

    def __post_init__(self) -> None:
        if self.step_models is not None:
            validate_step_models(self.step_models)
        if self.scoring_method not in get_args(ScoringMethod):
            raise ValueError(f"Invalid scoring_method: {self.scoring_method!r}")


@dataclass
class PipelineResult:
    """Final pipeline execution result."""

    summary: SummaryState
    assets: AssetsList
    flows: FlowsList
    threats: ThreatsList
    iterations_completed: int
    total_duration_seconds: float
    stopped_reason: str  # "max_iterations" | "gap_satisfied" | "timeout" | "provider_offline" | "dedup_saturated"


class PipelineRunner:
    """Orchestrates the threat modeling pipeline with iteration support."""

    def __init__(
        self,
        provider: LLMProvider,
        config: PipelineConfig,
        model_id: str,
        fast_provider: LLMProvider | None = None,
        persist_usage: bool = False,
    ):
        """Initialize pipeline runner.

        Args:
            provider: LLM provider for threat generation, gap analysis, and summarization.
            config: Pipeline configuration.
            model_id: Threat model ID for tracking.
            fast_provider: Optional cheaper/faster provider for extraction steps
                (assets, flows) and enrichment (attack trees, test cases).
                Falls back to ``provider`` when not set.
            persist_usage: Write a pipeline_runs audit row per instrumented
                step. Opt-in and False by default: `pipeline_runs.model_id`
                has a foreign key to `threat_models(id)`, so this must only
                be set when `model_id` already names a saved row — true for
                the web run route and per-threat enrichment, but not for the
                CLI, which generates its own `<file>-<timestamp>` run id and
                only creates the real threat_models row *after* the pipeline
                finishes (persist_pipeline_result). Turning this on for an
                unsaved model_id doesn't corrupt anything — the insert just
                fails on FOREIGN KEY constraint and is logged — but doing it
                on every step floods the log with one traceback per step.
        """
        self.provider = provider
        self.fast_provider = fast_provider or provider
        self.config = config
        self.model_id = model_id
        self.persist_usage = persist_usage
        self.start_time: datetime | None = None
        # Usage accounting (week 4a-1): every instrumented node call appends a
        # StepRun here; `last_usage` holds the most recent call's per-model
        # breakdown so the caller can attach it to that step's PipelineEvent.
        self._step_runs: list[StepRun] = []
        self.last_usage: list = []
        # Per-step routing (week 4a-2): config.step_models is merged onto
        # the provider's default map, not substituted for it — a step left
        # out of an override must keep its provider default.
        self._step_models = resolve_step_models(self.provider.name, config.step_models)
        # Circuit breaker: set once a fast-routed step hits a non-transient
        # ProviderError (auth failure, unknown model, bad request — anything
        # other than a ProviderTransientError: rate limit, timeout,
        # connection error or 5xx, which can reasonably succeed on a later
        # call). Once set, _provider_for stops trying the fast
        # model for the rest of this run — without it, a permanently broken
        # fast model (e.g. a FAST_MODEL_OPENAI the account has no access to)
        # pays one failed call *per step*, and per *enrichment call* under
        # --enrich (one attack-tree/test-case pair per threat).
        self._fast_disabled = False
        # Count of ProviderRefusalError occurrences, surfaced in RunUsage so
        # the bench harness and the UI can tell a refusal apart from any
        # other provider failure.
        self._refusal_count = 0

    def _note_refusal(self, e: ProviderError) -> None:
        """Increment the refusal counter exactly once per distinct
        ProviderRefusalError. Call this at the one catch site that will
        actually own each exception instance — never both the site that
        re-raises it and the site that later catches the re-raised copy."""
        if isinstance(e, ProviderRefusalError):
            self._refusal_count += 1

    def _provider_for(self, step: PipelineStep) -> LLMProvider:
        """Return the provider instance routed for `step` by self._step_models."""
        if self._fast_disabled:
            return self.provider
        return (
            self.fast_provider if self._step_models.get(step, "main") == "fast" else self.provider
        )

    async def _call_step(
        self,
        step: PipelineStep,
        iteration: int,
        build_coro: Callable[[LLMProvider], Awaitable[Any]],
        input_value: Any,
    ) -> tuple[Any, LLMProvider, "PipelineEvent | None"]:
        """Run a node on the provider routed for `step`, falling back to the
        main provider if the fast model fails.

        Returns (result, provider_used, fallback_event). fallback_event is
        None unless the fast model raised a ProviderError and the retry on
        main succeeded — the caller yields it as an "info" PipelineEvent
        before the step's normal "completed" event.
        """
        provider = self._provider_for(step)
        try:
            result = await self._instrument(
                step, iteration, provider, build_coro(provider), input_value
            )
            return result, provider, None
        except ProviderError as e:
            if provider is self.provider:
                # Re-raised as-is: the caller's own ProviderError handler
                # counts it (via _note_refusal) exactly once. Counting here
                # too would double it for every main-model failure.
                raise
            self._note_refusal(e)
            logger.warning(
                "Fast model failed for step %s, retrying on main model: %s", step.value, e
            )
            message = f"Fast model unavailable for {step.value} ({e}) — retried on main model"
            # Transient failures can clear up on a later call; anything else
            # (auth failure, unknown model, bad request, ...) won't, so stop
            # spending a failed call on the fast model for every remaining
            # step/enrichment call in this run.
            if not isinstance(e, ProviderTransientError):
                self._fast_disabled = True
                message += "; fast routing disabled for the rest of this run"
            fallback_event = PipelineEvent(step=step, status="info", message=message)
            result = await self._instrument(
                step, iteration, self.provider, build_coro(self.provider), input_value
            )
            return result, self.provider, fallback_event

    async def _instrument(
        self,
        step: "PipelineStep",
        iteration: int,
        provider: LLMProvider,
        coro: Any,
        input_value: Any,
    ) -> Any:
        """Run a node coroutine inside a usage-collection scope and record a
        pipeline_runs audit row — on failure too (any exception, not just
        ProviderError: a cancelled or timed-out call still billed whatever
        the provider had already recorded). Sets ``self.last_usage`` so the
        caller can attach ``{"model", "usage"}`` to its own PipelineEvent.
        """
        t0 = time.monotonic()
        status = "failed"
        result = None
        with collect_usage() as records:
            try:
                result = await coro
                status = "completed"
                self.last_usage = summarize_usage(records)
            finally:
                await self._record_step(
                    step, iteration, provider, status, t0, input_value, result, records
                )
        return result

    async def _record_step(
        self,
        step: "PipelineStep",
        iteration: int,
        provider: LLMProvider,
        status: str,
        t0: float,
        input_value: Any,
        output_value: Any,
        records: list,
    ) -> None:
        """Append a StepRun and, when ``self.persist_usage`` is set, persist it
        to pipeline_runs. Persistence is non-fatal — a DB error here must
        never interrupt the pipeline — and is also skipped outright when no
        connection is already up (see ConnectionManager.is_initialized) so a
        bare unit test of the runner never lazily opens the real on-disk
        database as a side effect. ``persist_usage=False`` (the CLI's case,
        before its own threat_models row exists) skips the write entirely
        rather than attempting and swallowing a FOREIGN KEY failure on every
        single step."""
        duration_ms = int((time.monotonic() - t0) * 1000)
        model_usage = summarize_usage(records)
        step_run = StepRun(
            step=step.value,
            iteration=iteration,
            status=status,
            provider=provider.name,
            model=provider.model,
            duration_ms=duration_ms,
            input_hash=_hash_value(input_value),
            output_hash=_hash_value(output_value) if output_value is not None else "",
            usage=model_usage,
        )
        self._step_runs.append(step_run)
        if not self.persist_usage:
            return
        from backend.db.connection import db  # local import: mirrors the RAG project-id

        if not db.is_initialized:
            return
        try:
            from backend.db import crud

            total = sum(u.total_tokens for u in model_usage)
            await crud.create_pipeline_run(
                model_id=self.model_id,
                iteration=iteration,
                step=step.value,
                input_hash=step_run.input_hash,
                output_hash=step_run.output_hash,
                provider=provider.name,
                duration_ms=duration_ms,
                tokens_used=total or None,
                model=provider.model,
                input_tokens=sum(u.input_tokens for u in model_usage) or None,
                output_tokens=sum(u.output_tokens for u in model_usage) or None,
                cache_read_tokens=sum(u.cache_read_tokens for u in model_usage) or None,
                cache_write_tokens=sum(u.cache_write_tokens for u in model_usage) or None,
            )
        except Exception:
            logger.warning(
                "Failed to persist pipeline_runs audit row for step %s (non-fatal)",
                step.value,
                exc_info=True,
            )

    def _check_time_limit(self) -> bool:
        """Check if execution time limit has been reached."""
        if not self.start_time:
            return False

        elapsed = (datetime.now() - self.start_time).total_seconds()
        return elapsed >= (self.config.max_execution_time_minutes * 60)

    async def run(
        self,
        description: str,
        framework: Framework,
        architecture_diagram: str | None = None,
        assumptions: list[str] | None = None,
        code_context: CodeContext | None = None,
        diagrams: list[DiagramData] | None = None,
        stop_after: StopAfter | None = None,
        seeded_assets: AssetsList | None = None,
        seeded_flows: FlowsList | None = None,
        seeded_threats: ThreatsList | None = None,
        dependency_context: DependencyContext | None = None,
        dependency_manifest: dict | None = None,
        dependency_lockfile: dict | None = None,
        dependency_source_mode: str = "npm",
    ) -> AsyncGenerator[PipelineEvent, None]:
        """Run the complete threat modeling pipeline with SSE events.

        Args:
            description: System description
            framework: STRIDE or MAESTRO framework
            architecture_diagram: DEPRECATED - use diagrams instead
            assumptions: Optional list of assumptions
            code_context: Optional code context from MCP
            diagrams: Optional diagrams (PNG/JPG/Mermaid), 1 or more. Validated
                as a set (count/total-size caps, duplicate-name resolution)
                at the start of this call.
            stop_after: If "extraction", stop after assets/flows are extracted and
                persisted, then yield a complete event. Used by the /extract endpoint
                to populate context without running threat generation.
            seeded_assets: Pre-edited assets to use instead of running LLM extraction.
                When provided the EXTRACT_ASSETS step is skipped.
            seeded_flows: Pre-edited flows/boundaries to use instead of running LLM
                extraction. When provided the EXTRACT_FLOWS step is skipped.
            seeded_threats: Known threats to seed the catalog before the iteration loop.
                Each threat is tagged with _source="seeded". The iteration loop deduplicates
                new LLM threats against these, so overlapping threats are not duplicated.
            dependency_context: Pre-analyzed dependency capabilities. When provided,
                the ANALYZE_DEPENDENCIES step is skipped and this is used as-is.
            dependency_manifest: Parsed package.json to analyze when
                dependency_context isn't already provided.
            dependency_lockfile: Parsed package-lock.json (optional) used to pin
                dependency_manifest versions.
            dependency_source_mode: "npm" | "github" | "both" — which source(s)
                to fetch and scan each direct dependency with.

        Yields:
            PipelineEvent for each step and iteration
        """
        self.start_time = datetime.now()
        logger.info(
            "Pipeline started: model=%s framework=%s iterations=%d has_ai=%s",
            self.model_id,
            framework.value,
            self.config.max_iterations,
            self.config.has_ai_components,
        )

        # This is a backstop, not the primary check — callers (the run route,
        # the CLI) are expected to validate before invoking the pipeline at
        # all. A failure here still has to end the SSE stream with a proper
        # failed event rather than an unhandled exception breaking the
        # generator (mirrors the except Exception handling in the /extract
        # route's event_generator).
        if diagrams:
            try:
                diagrams = validate_diagram_set(list(diagrams))
            except DiagramValidationError as e:
                yield PipelineEvent(
                    step=PipelineStep.COMPLETE,
                    status="failed",
                    message=f"Invalid diagram set: {e}",
                )
                return

        # Image support is per provider instance (Ollama never sends images;
        # Bedrock decides per model — see BedrockProvider.supports_images).
        # When any diagram is an image and the provider can't take it,
        # degrade: skip sending image bytes on the calls that would
        # otherwise carry them (with_images=False) and tell the caller which
        # diagrams were ignored. Mermaid diagrams are unaffected either way.
        images_supported = self.provider.supports_images
        if diagrams and not images_supported:
            ignored = [d.name for d in diagrams if d.format != DiagramFormat.MERMAID]
            if ignored:
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE,
                    status="info",
                    message=(
                        f"The {self.provider.name} provider ({self.provider.model}) doesn't "
                        f"support images; {len(ignored)} image diagram(s) skipped, Mermaid "
                        "diagrams are used."
                    ),
                    data={"warning": "vision_unsupported", "ignored": ignored},
                )

        # The main provider may support images while the fast provider
        # doesn't (or vice versa) — each step's with_images is already
        # gated on the provider it actually runs on (images_supported and
        # p.supports_images below), but that would otherwise degrade
        # silently for whichever image-eligible steps are fast-routed.
        if (
            diagrams
            and images_supported
            and self.fast_provider is not self.provider
            and not self.fast_provider.supports_images
        ):
            ignored = [d.name for d in diagrams if d.format != DiagramFormat.MERMAID]
            fast_image_steps = [
                step
                for step in (
                    PipelineStep.SUMMARIZE,
                    PipelineStep.EXTRACT_ASSETS,
                    PipelineStep.EXTRACT_FLOWS,
                )
                if self._step_models.get(step, "main") == "fast"
            ]
            if ignored and fast_image_steps:
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE,
                    status="info",
                    message=(
                        f"The fast provider ({self.fast_provider.name} "
                        f"{self.fast_provider.model}) doesn't support images; "
                        f"{len(ignored)} image diagram(s) skipped on "
                        f"{', '.join(s.value for s in fast_image_steps)}, Mermaid "
                        "diagrams are used there."
                    ),
                    data={
                        "warning": "vision_unsupported",
                        "ignored": ignored,
                        "steps": [s.value for s in fast_image_steps],
                    },
                )

        # Iteration state is initialized here (not inside the try) so that a
        # ProviderError in the pre-loop steps can still fall through to the rule
        # engine and complete event with sensible defaults.
        provider_failed = False
        current_threats: ThreatsList | None = None
        cumulative_threats = ThreatsList(threats=[])
        iteration = 1

        # Pre-load seeded threats: tag each with _source="seeded" and add to the
        # cumulative catalog so the iteration loop deduplicates LLM output against them.
        if seeded_threats and seeded_threats.threats:
            for t in seeded_threats.threats:
                t.source = "seeded"
            cumulative_threats.threats.extend(seeded_threats.threats)
            yield PipelineEvent(
                step=PipelineStep.GENERATE_THREATS,
                status="info",
                message=f"Loaded {len(seeded_threats.threats)} seeded threats into catalog",
                data={"seeded_threat_count": len(seeded_threats.threats)},
            )
        iterations_completed = 0
        stopped_reason = "max_iterations"
        gaps: list[str] = []
        code_summary = None
        shared_ctx: str | None = None
        consecutive_zero = 0

        # Step 0: Analyze Dependencies. No LLM involved, so it runs before the
        # provider-dependent steps and outside their ProviderError handling.
        # A pre-analyzed context is used as-is; a raw manifest is analyzed here.
        # Any failure (network, a hostile tarball, a malformed manifest, or
        # exceeding deps_analysis_timeout_seconds) degrades exactly like an
        # unavailable MCP code source: a warning event, dependency_context=None,
        # and the pipeline continues without it.
        #
        # Skipped entirely when stop_after="extraction": that path returns
        # before build_shared_context/the rule/dependency-threat passes ever
        # run, so the analysis result would just be discarded unused.
        if (
            dependency_context is None
            and dependency_manifest is not None
            and stop_after != "extraction"
        ):
            yield PipelineEvent(
                step=PipelineStep.ANALYZE_DEPENDENCIES,
                status="started",
                message="Analyzing dependency capabilities...",
            )
            try:
                # analyze_manifest() itself budgets each package against
                # `deadline` and returns partial results (finished packages
                # plus skip reason "time_budget" for the rest) instead of an
                # all-or-nothing failure. The outer wait_for is a hard
                # backstop for anything analyze_manifest doesn't itself
                # budget (e.g. it hanging before the per-package semaphore is
                # ever reached) — expected to be a no-op in the normal case.
                # Its timeout must exceed the deadline by
                # _DEPS_ANALYSIS_BACKSTOP_GRACE_S, not equal it: a package
                # cancelled right at the deadline can take several seconds to
                # actually finish cleaning up (see the constant's docstring),
                # and an equal timeout fires mid-cleanup, discarding the
                # partial results analyze_manifest was about to return.
                deadline = time.monotonic() + settings.deps_analysis_timeout_seconds
                dependency_context = await asyncio.wait_for(
                    analyze_manifest(
                        dependency_manifest,
                        dependency_lockfile,
                        source_mode=dependency_source_mode,
                        deadline=deadline,
                    ),
                    timeout=settings.deps_analysis_timeout_seconds
                    + _DEPS_ANALYSIS_BACKSTOP_GRACE_S,
                )
                yield PipelineEvent(
                    step=PipelineStep.ANALYZE_DEPENDENCIES,
                    status="completed",
                    message=(
                        f"Analyzed {len(dependency_context.packages)} direct dependencies, "
                        f"{len(dependency_context.skipped)} skipped"
                    ),
                    data={
                        "package_count": len(dependency_context.packages),
                        "skipped_count": len(dependency_context.skipped),
                    },
                )
            except TimeoutError:
                logger.warning(
                    "Dependency analysis exceeded %ds timeout",
                    settings.deps_analysis_timeout_seconds,
                )
                dependency_context = None
                yield PipelineEvent(
                    step=PipelineStep.ANALYZE_DEPENDENCIES,
                    status="info",
                    message=(
                        f"Dependency analysis timed out after "
                        f"{settings.deps_analysis_timeout_seconds}s — continuing without it"
                    ),
                    data={"error": "timeout"},
                )
            except Exception as e:
                logger.warning("Dependency analysis failed: %s", e)
                dependency_context = None
                yield PipelineEvent(
                    step=PipelineStep.ANALYZE_DEPENDENCIES,
                    status="info",
                    message=f"Dependency analysis unavailable ({e}) — continuing without it",
                    data={"error": str(e)},
                )

        try:
            # Steps 1-3: Summarize, Extract Assets, Extract Flows.
            # A ProviderError here means the LLM is completely unreachable.
            # Catch it before it propagates to the outer handler so the pipeline
            # can continue in rule-engine-only mode.
            try:
                # Step 1: Summarize (+ code summarization if code context provided)
                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE,
                    status="started",
                    message="Generating system summary...",
                )

                # Run summarize; extract code summary deterministically if code available.
                # The LLM-backed summarize_code() is replaced by _deterministic_code_summary()
                # to save one API call per run. Pattern matching covers the security-relevant
                # signals (tech stack, entry points, auth patterns, anti-patterns) without
                # the token cost of a second LLM call at this stage.
                if code_context:
                    summary, summarize_provider, fallback_event = await self._call_step(
                        PipelineStep.SUMMARIZE,
                        0,
                        lambda p: nodes.summarize(
                            description=description,
                            architecture_diagram=architecture_diagram,
                            assumptions=assumptions,
                            code_context=code_context,
                            provider=p,
                            diagrams=diagrams,
                            with_images=images_supported and p.supports_images,
                            temperature=self.config.temperature,
                        ),
                        {"description": description, "assumptions": assumptions},
                    )
                    if fallback_event:
                        yield fallback_event

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE,
                        status="completed",
                        message=f"Summary generated: {len(summary.summary)} chars",
                        data={
                            "summary": summary.summary,
                            "model": summarize_provider.model,
                            "usage": [u.model_dump() for u in self.last_usage],
                        },
                    )

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE_CODE,
                        status="started",
                        message="Analyzing code structure and security patterns...",
                    )

                    # Known limitation: nodes.summarize_code() catches
                    # ProviderError itself and returns a deterministic
                    # fallback rather than re-raising (see
                    # backend/pipeline/nodes/summary.py). If this step is
                    # ever routed to "fast" via step_models and the fast
                    # model fails, _call_step below never sees the
                    # ProviderError to retry on main — the deterministic
                    # fallback silently wins instead. Not a behaviour change
                    # today (SUMMARIZE_CODE defaults to "main" and nothing
                    # overrides it), but a future fast-routing change here
                    # should make the node re-raise so fast → main → the
                    # deterministic fallback runs in that priority order.
                    code_summary, summarize_code_provider, fallback_event = await self._call_step(
                        PipelineStep.SUMMARIZE_CODE,
                        0,
                        lambda p: nodes.summarize_code(
                            code_context=code_context,
                            provider=p,
                            temperature=self.config.temperature,
                        ),
                        code_context,
                    )
                    if fallback_event:
                        yield fallback_event

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE_CODE,
                        status="completed",
                        message=f"Code analyzed: {len(code_summary.tech_stack)} technologies, {len(code_summary.entry_points)} entry points",
                        data={
                            "tech_stack": code_summary.tech_stack,
                            "entry_points": code_summary.entry_points,
                            "code_summary": code_summary,
                            "model": summarize_code_provider.model,
                            "usage": [u.model_dump() for u in self.last_usage],
                        },
                    )
                else:
                    summary, summarize_provider, fallback_event = await self._call_step(
                        PipelineStep.SUMMARIZE,
                        0,
                        lambda p: nodes.summarize(
                            description=description,
                            architecture_diagram=architecture_diagram,
                            assumptions=assumptions,
                            code_context=None,
                            provider=p,
                            diagrams=diagrams,
                            with_images=images_supported and p.supports_images,
                            temperature=self.config.temperature,
                        ),
                        {"description": description, "assumptions": assumptions},
                    )
                    code_summary = None
                    if fallback_event:
                        yield fallback_event

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE,
                        status="completed",
                        message=f"Summary generated: {len(summary.summary)} chars",
                        data={
                            "summary": summary.summary,
                            "model": summarize_provider.model,
                            "usage": [u.model_dump() for u in self.last_usage],
                        },
                    )

                # Step 2: Extract Assets (skip if pre-edited assets injected)
                if seeded_assets is not None:
                    assets = seeded_assets
                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_ASSETS,
                        status="completed",
                        message=f"Using {len(assets.assets)} pre-edited assets",
                        data={"asset_count": len(assets.assets), "assets": assets},
                    )
                else:
                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_ASSETS,
                        status="started",
                        message="Identifying assets and entities...",
                    )

                    assets, assets_provider, fallback_event = await self._call_step(
                        PipelineStep.EXTRACT_ASSETS,
                        0,
                        lambda p: nodes.extract_assets(
                            summary=summary.summary,
                            description=description,
                            architecture_diagram=architecture_diagram,
                            assumptions=assumptions,
                            framework=framework,
                            provider=p,
                            temperature=self.config.temperature,
                            code_summary=code_summary,
                            diagrams=diagrams,
                            with_images=images_supported and p.supports_images,
                        ),
                        {"summary": summary.summary, "description": description},
                    )
                    if fallback_event:
                        yield fallback_event

                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_ASSETS,
                        status="completed",
                        message=f"Identified {len(assets.assets)} assets/entities",
                        data={
                            "asset_count": len(assets.assets),
                            "assets": assets,
                            "model": assets_provider.model,
                            "usage": [u.model_dump() for u in self.last_usage],
                        },
                    )

                # Step 3: Extract Flows (skip if pre-edited flows injected)
                if seeded_flows is not None:
                    flows = seeded_flows
                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_FLOWS,
                        status="completed",
                        message=f"Using {len(flows.data_flows)} pre-edited flows, {len(flows.trust_boundaries)} boundaries",
                        data={
                            "flow_count": len(flows.data_flows),
                            "boundary_count": len(flows.trust_boundaries),
                            "flows": flows,
                        },
                    )
                else:
                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_FLOWS,
                        status="started",
                        message="Extracting data flows and trust boundaries...",
                    )

                    flows, flows_provider, fallback_event = await self._call_step(
                        PipelineStep.EXTRACT_FLOWS,
                        0,
                        lambda p: nodes.extract_flows(
                            summary=summary.summary,
                            description=description,
                            architecture_diagram=architecture_diagram,
                            assumptions=assumptions,
                            assets=assets,
                            provider=p,
                            temperature=self.config.temperature,
                            code_summary=code_summary,
                            diagrams=diagrams,
                            with_images=images_supported and p.supports_images,
                        ),
                        {"summary": summary.summary, "assets": assets},
                    )
                    if fallback_event:
                        yield fallback_event

                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_FLOWS,
                        status="completed",
                        message=f"Identified {len(flows.data_flows)} flows, {len(flows.trust_boundaries)} boundaries",
                        data={
                            "flow_count": len(flows.data_flows),
                            "boundary_count": len(flows.trust_boundaries),
                            "flows": flows,
                            "model": flows_provider.model,
                            "usage": [u.model_dump() for u in self.last_usage],
                        },
                    )

                # stop_after="extraction" — persist and return without threat generation
                if stop_after == "extraction":
                    yield PipelineEvent(
                        step=PipelineStep.COMPLETE,
                        status="completed",
                        message="Extraction complete. Context is ready for review.",
                        data={
                            "asset_count": len(assets.assets),
                            "flow_count": len(flows.data_flows),
                            "boundary_count": len(flows.trust_boundaries),
                        },
                    )
                    return

                # Build stable context once — reused as cacheable prefix for all
                # generate_threats() and gap_analysis() calls in the iteration loop.
                shared_ctx = build_shared_context(
                    description=description,
                    architecture_diagram=architecture_diagram,
                    assumptions=assumptions,
                    assets=assets,
                    flows=flows,
                    code_summary=code_summary,
                    diagrams=diagrams,
                    images_supported=images_supported,
                    framework=framework,
                    dependency_context=dependency_context,
                )

            except ProviderError as e:
                # LLM provider is offline — degrade gracefully to rule-engine-only.
                # Use the original description as a minimal summary so the rule
                # engine still has text to match keywords against.
                self._note_refusal(e)
                provider_failed = True
                stopped_reason = "provider_offline"
                summary = SummaryState(summary=description)
                assets = AssetsList(assets=[])
                flows = FlowsList(data_flows=[], trust_boundaries=[], threat_sources=[])
                logger.warning("Provider unavailable during pre-loop steps: %s", e)
                yield PipelineEvent(
                    step=PipelineStep.RULE_ENGINE,
                    status="info",
                    message=(
                        f"LLM provider unavailable ({e}) — switching to rule-engine-only mode"
                    ),
                    data=_provider_error_event_data(e),
                )

            # Step 4: Iterative Threat Generation
            # Iteration semantics:
            # - Each iteration generates NEW threats (not existing + new)
            # - The "improve" prompt asks LLM to find threats that were missed
            # - current_threats = latest iteration's output (NEW threats only)
            # - cumulative_threats = all threats from all iterations
            # - existing_threats passed to LLM = cumulative from previous iterations
            # - Gap analysis uses cumulative to assess full coverage

            # RAG fetch is hoisted here: description + assets are stable across all
            # iterations, so fetching once and reusing is semantically equivalent
            # and saves (max_iterations - 1) vector queries + ~1-2k prompt tokens
            # per iteration. Skip entirely when keywords produce no rule-engine hits
            # (no RAG hits expected either in that case).
            if self.config.enable_rag and not provider_failed:
                from backend.db.crud_projects import resolve_project_id_from_model

                try:
                    # Bounded like other DB operations (RULES.md: 5s default)
                    # so a slow/unavailable DB degrades RAG scoping rather than
                    # blocking the whole pipeline run.
                    project_id = await asyncio.wait_for(
                        resolve_project_id_from_model(self.model_id), timeout=5.0
                    )
                except Exception as e:
                    logger.warning(f"Could not resolve project_id for RAG scoping: {e}")
                    project_id = None
                assets_text = " ".join(a.name for a in assets.assets)
                rag_context = await fetch_rag_context(
                    description,
                    assets_text=assets_text,
                    limit=settings.rag_top_k,
                    project_id=project_id,
                )
            else:
                rag_context = None

            if not provider_failed:
                while iteration <= self.config.max_iterations:
                    logger.info(
                        "Iteration %d/%d started: cumulative_threats=%d",
                        iteration,
                        self.config.max_iterations,
                        len(cumulative_threats.threats),
                    )
                    # Check time limit
                    if self._check_time_limit():
                        yield PipelineEvent(
                            step=PipelineStep.ITERATE,
                            status="info",
                            message=f"Time limit reached after {iterations_completed} iterations",
                            iteration=iteration,
                        )
                        stopped_reason = "timeout"
                        break

                    # Generate threats
                    # If has_ai_components=True and framework=STRIDE, run both STRIDE and MAESTRO
                    if self.config.has_ai_components and framework == Framework.STRIDE:
                        # Dual framework execution
                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="started",
                            message=f"Generating STRIDE threats (iteration {iteration}/{self.config.max_iterations})...",
                            iteration=iteration,
                        )

                        # Generate STRIDE threats
                        try:
                            stride_threats = await self._instrument(
                                PipelineStep.GENERATE_THREATS,
                                iteration,
                                self.provider,
                                nodes.generate_threats(
                                    description=description,
                                    architecture_diagram=architecture_diagram,
                                    assumptions=assumptions,
                                    assets=assets,
                                    flows=flows,
                                    framework=Framework.STRIDE,
                                    provider=self.provider,
                                    existing_threats=current_threats
                                    if iteration > 1
                                    else (
                                        cumulative_threats if cumulative_threats.threats else None
                                    ),
                                    gap_analysis=gaps[-1] if gaps else None,
                                    rag_context=rag_context,
                                    temperature=self.config.temperature,
                                    code_summary=code_summary,
                                    diagrams=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                    shared_context=shared_ctx,
                                    scoring_method=self.config.scoring_method,
                                ),
                                {
                                    "iteration": iteration,
                                    "framework": "STRIDE",
                                    "gap": gaps[-1] if gaps else None,
                                },
                            )
                        except ProviderError as e:
                            self._note_refusal(e)
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            logger.warning(
                                "Provider unavailable during STRIDE generation (iteration %d): %s",
                                iteration,
                                e,
                            )
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data=_provider_error_event_data(e),
                            )
                            break

                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="completed",
                            message=f"Generated {len(stride_threats.threats)} STRIDE threats",
                            iteration=iteration,
                            data={
                                "threat_count": len(stride_threats.threats),
                                "framework": "STRIDE",
                                "threats": stride_threats,
                                "model": self.provider.model,
                                "usage": [u.model_dump() for u in self.last_usage],
                            },
                        )

                        # Generate MAESTRO threats for AI/ML components
                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="started",
                            message=f"Generating MAESTRO threats for AI/ML components (iteration {iteration}/{self.config.max_iterations})...",
                            iteration=iteration,
                        )

                        try:
                            maestro_threats = await self._instrument(
                                PipelineStep.GENERATE_THREATS,
                                iteration,
                                self.provider,
                                nodes.generate_threats(
                                    description=description,
                                    architecture_diagram=architecture_diagram,
                                    assumptions=assumptions,
                                    assets=assets,
                                    flows=flows,
                                    framework=Framework.MAESTRO,
                                    provider=self.provider,
                                    existing_threats=current_threats
                                    if iteration > 1
                                    else (
                                        cumulative_threats if cumulative_threats.threats else None
                                    ),
                                    gap_analysis=gaps[-1] if gaps else None,
                                    rag_context=rag_context,
                                    temperature=self.config.temperature,
                                    code_summary=code_summary,
                                    diagrams=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                    shared_context=shared_ctx,
                                    scoring_method=self.config.scoring_method,
                                ),
                                {
                                    "iteration": iteration,
                                    "framework": "MAESTRO",
                                    "gap": gaps[-1] if gaps else None,
                                },
                            )
                        except ProviderError as e:
                            self._note_refusal(e)
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            # Preserve STRIDE threats from this iteration before yielding
                            # so the event stream is monotonic (state updated, then announced).
                            cumulative_threats.threats.extend(stride_threats.threats)
                            logger.warning(
                                "Provider unavailable during MAESTRO generation (iteration %d): %s",
                                iteration,
                                e,
                            )
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data=_provider_error_event_data(e),
                            )
                            break

                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="completed",
                            message=f"Generated {len(maestro_threats.threats)} MAESTRO threats",
                            iteration=iteration,
                            data={
                                "threat_count": len(maestro_threats.threats),
                                "framework": "MAESTRO",
                                "threats": maestro_threats,
                                "model": self.provider.model,
                                "usage": [u.model_dump() for u in self.last_usage],
                            },
                        )

                        # Merge and deduplicate across frameworks
                        combined = stride_threats + maestro_threats
                        dedup_result = deduplicate_threats(
                            combined,
                            threshold=self.config.similarity_threshold,
                        )
                        current_threats = dedup_result.threats

                        if dedup_result.removed_count > 0:
                            yield PipelineEvent(
                                step=PipelineStep.GENERATE_THREATS,
                                status="info",
                                message=f"Removed {dedup_result.removed_count} cross-framework duplicates",
                                iteration=iteration,
                                data={"duplicates_removed": dedup_result.removed_count},
                            )

                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="info",
                            message=f"Combined {len(current_threats.threats)} new threats (STRIDE + MAESTRO)",
                            iteration=iteration,
                            data={
                                "threat_count": len(current_threats.threats),
                                "threats": current_threats,
                                "framework": "COMBINED",
                            },
                        )
                    else:
                        # Single framework execution
                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="started",
                            message=f"Generating threats (iteration {iteration}/{self.config.max_iterations})...",
                            iteration=iteration,
                        )

                        try:
                            current_threats = await self._instrument(
                                PipelineStep.GENERATE_THREATS,
                                iteration,
                                self.provider,
                                nodes.generate_threats(
                                    description=description,
                                    architecture_diagram=architecture_diagram,
                                    assumptions=assumptions,
                                    assets=assets,
                                    flows=flows,
                                    framework=framework,
                                    provider=self.provider,
                                    existing_threats=current_threats
                                    if iteration > 1
                                    else (
                                        cumulative_threats if cumulative_threats.threats else None
                                    ),
                                    gap_analysis=gaps[-1] if gaps else None,
                                    rag_context=rag_context,
                                    temperature=self.config.temperature,
                                    code_summary=code_summary,
                                    diagrams=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                    shared_context=shared_ctx,
                                    scoring_method=self.config.scoring_method,
                                ),
                                {
                                    "iteration": iteration,
                                    "framework": framework.value,
                                    "gap": gaps[-1] if gaps else None,
                                },
                            )
                        except ProviderError as e:
                            self._note_refusal(e)
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            logger.warning(
                                "Provider unavailable during threat generation (iteration %d): %s",
                                iteration,
                                e,
                            )
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data=_provider_error_event_data(e),
                            )
                            break

                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="completed",
                            message=f"Generated {len(current_threats.threats)} new threats",
                            iteration=iteration,
                            data={
                                "threat_count": len(current_threats.threats),
                                "threats": current_threats,
                                "model": self.provider.model,
                                "usage": [u.model_dump() for u in self.last_usage],
                            },
                        )

                    # Zero-threat detection: fires after the provider returns, before
                    # cross-iteration dedup. Measures what the LLM returned this iteration.
                    # The saturation gate cannot catch this: removed_count=0 gives
                    # saturation_ratio=0, so it never trips on all-zero iterations.
                    # Detection is informational only; a stop condition is not added here
                    # because two consecutive zeros is a signal worth surfacing but not
                    # a definitive failure mode on its own.
                    if len(current_threats.threats) == 0:
                        consecutive_zero += 1
                        if consecutive_zero >= 2:
                            yield PipelineEvent(
                                step=PipelineStep.ITERATE,
                                status="info",
                                message=f"Zero threats produced in {consecutive_zero} consecutive iterations",
                                iteration=iteration,
                                data={"consecutive_zero_iterations": consecutive_zero},
                            )
                        else:
                            yield PipelineEvent(
                                step=PipelineStep.ITERATE,
                                status="info",
                                message=f"Provider returned no threats in iteration {iteration}",
                                iteration=iteration,
                                data={"warning": "zero_threats", "iteration": iteration},
                            )
                    else:
                        consecutive_zero = 0

                    # Deduplicate against cumulative threats (prior iterations or seeded threats).
                    # When seeded threats were pre-loaded, cumulative_threats is non-empty even on
                    # iteration 1, so always dedup when there is something to check against.
                    if cumulative_threats.threats:
                        dedup_result = deduplicate_threats(
                            current_threats,
                            existing_threats=cumulative_threats,
                            threshold=self.config.similarity_threshold,
                        )
                        cumulative_threats.threats.extend(dedup_result.threats.threats)
                        logger.info(
                            "Iteration %d dedup: new=%d removed=%d cumulative=%d",
                            iteration,
                            len(current_threats.threats),
                            dedup_result.removed_count,
                            len(cumulative_threats.threats),
                        )
                        if dedup_result.removed_count > 0:
                            yield PipelineEvent(
                                step=PipelineStep.GENERATE_THREATS,
                                status="info",
                                message=f"Removed {dedup_result.removed_count} cross-iteration duplicates",
                                iteration=iteration,
                                data={"duplicates_removed": dedup_result.removed_count},
                            )
                        # Saturation stop: if most of this iteration's threats are
                        # duplicates, further iterations are unlikely to find novel threats.
                        # iteration > 1 guard prevents seeds pre-loaded into cumulative
                        # from triggering saturation on the very first LLM pass.
                        saturation_ratio = dedup_result.removed_count / max(
                            1, len(current_threats.threats)
                        )
                        if (
                            saturation_ratio >= self.config.dedup_saturation_threshold
                            and iteration > 1
                            and iteration >= self.config.min_iterations
                        ):
                            yield PipelineEvent(
                                step=PipelineStep.GENERATE_THREATS,
                                status="info",
                                message=(
                                    f"Dedup saturation reached ({saturation_ratio:.0%} of new threats "
                                    f"were duplicates) — stopping after iteration {iteration}"
                                ),
                                iteration=iteration,
                                data={
                                    "saturation_ratio": round(saturation_ratio, 3),
                                    "duplicates_removed": dedup_result.removed_count,
                                    "stopped_reason": "dedup_saturated",
                                },
                            )
                            stopped_reason = "dedup_saturated"
                            iterations_completed = iteration
                            break
                    else:
                        cumulative_threats.threats.extend(current_threats.threats)
                        logger.info(
                            "Iteration %d dedup: new=%d cumulative=%d",
                            iteration,
                            len(current_threats.threats),
                            len(cumulative_threats.threats),
                        )
                    iterations_completed = iteration  # Track before potential break in gap analysis

                    # Show cumulative count only from iteration 2+ (iteration 1 is same as current)
                    if iteration > 1:
                        yield PipelineEvent(
                            step=PipelineStep.GENERATE_THREATS,
                            status="info",
                            message=f"Total threats across all iterations: {len(cumulative_threats.threats)}",
                            iteration=iteration,
                            data={"cumulative_threat_count": len(cumulative_threats.threats)},
                        )

                    # Gap Analysis (only if not final iteration)
                    if iteration < self.config.max_iterations:
                        # Deterministic short-circuit: if every STRIDE category has >= 2
                        # threats the catalog is structurally balanced and LLM gap analysis
                        # is unlikely to find meaningful holes (saves ~1536 max-token call).
                        # Only applies to STRIDE framework; MAESTRO coverage is asymmetric.
                        # Exclude pre-loaded seeded threats from the balance check:
                        # seeds may already cover all STRIDE categories, which would
                        # short-circuit gap analysis before the LLM runs even once.
                        _llm_threats = ThreatsList(
                            threats=[t for t in cumulative_threats.threats if t.source != "seeded"]
                        )
                        if (
                            framework == Framework.STRIDE
                            and _is_stride_coverage_balanced(_llm_threats)
                            and iteration >= self.config.min_iterations
                        ):
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message="All STRIDE categories covered — skipping gap analysis",
                                iteration=iteration,
                                data={
                                    "stop": True,
                                    "gap": "Coverage balanced across all STRIDE categories",
                                },
                            )
                            stopped_reason = "gap_satisfied"
                            break

                        yield PipelineEvent(
                            step=PipelineStep.GAP_ANALYSIS,
                            status="started",
                            message="Analyzing threat coverage gaps...",
                            iteration=iteration,
                        )

                        try:
                            gap_result = await self._instrument(
                                PipelineStep.GAP_ANALYSIS,
                                iteration,
                                self.provider,
                                nodes.gap_analysis(
                                    description=description,
                                    architecture_diagram=architecture_diagram,
                                    assumptions=assumptions,
                                    assets=assets,
                                    flows=flows,
                                    threats=cumulative_threats,
                                    framework=framework,
                                    provider=self.provider,
                                    previous_gaps=gaps[
                                        -2:
                                    ],  # cap: only last 2 gaps to bound prompt growth
                                    temperature=self.config.temperature,
                                    code_summary=code_summary,
                                    diagrams=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                    shared_context=shared_ctx,
                                ),
                                {
                                    "iteration": iteration,
                                    "threat_count": len(cumulative_threats.threats),
                                },
                            )
                        except ProviderError as e:
                            self._note_refusal(e)
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            logger.warning(
                                "Provider unavailable during gap analysis (iteration %d): %s",
                                iteration,
                                e,
                            )
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable during gap analysis ({e}) — "
                                    "switching to rule-engine-only mode"
                                ),
                                data=_provider_error_event_data(e),
                            )
                            break

                        if gap_result.stop and iteration >= self.config.min_iterations:
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message="Gap analysis satisfied - stopping iterations",
                                iteration=iteration,
                                data={
                                    "stop": True,
                                    "gap": gap_result.gap,
                                    "model": self.provider.model,
                                    "usage": [u.model_dump() for u in self.last_usage],
                                },
                            )
                            stopped_reason = "gap_satisfied"
                            break
                        elif gap_result.stop:
                            # gap_result.stop=True but min_iterations floor prevents stopping.
                            # gap_result.gap is None in this case — don't append it.
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message=(
                                    f"Gap analysis satisfied but min_iterations floor "
                                    f"({self.config.min_iterations}) requires continuing"
                                ),
                                iteration=iteration,
                                data={
                                    "stop": False,
                                    "gap": None,
                                    "model": self.provider.model,
                                    "usage": [u.model_dump() for u in self.last_usage],
                                },
                            )
                        else:
                            gaps.append(gap_result.gap)
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message=f"Gap identified: {gap_result.gap[:100]}...",
                                iteration=iteration,
                                data={
                                    "stop": False,
                                    "gap": gap_result.gap,
                                    "model": self.provider.model,
                                    "usage": [u.model_dump() for u in self.last_usage],
                                },
                            )

                    iteration += 1

            # Rule engine pass: run deterministic pattern matching and merge
            # unique findings into cumulative_threats. Runs regardless of LLM success
            # because it catches known patterns the LLM may have missed.
            yield PipelineEvent(
                step=PipelineStep.RULE_ENGINE,
                status="started",
                message="Running deterministic rule engine...",
            )

            rule_threats = run_rule_engine(
                description,
                framework,
                max_patterns=settings.rag_top_k,
                collections=set(self.config.seed_collections)
                if self.config.seed_collections
                else None,
            )

            if rule_threats.threats:
                pre_merge_count = len(cumulative_threats.threats)
                cumulative_threats = merge_rule_and_llm_threats(
                    rule_threats,
                    cumulative_threats,
                    threshold=self.config.similarity_threshold,
                )
                added = len(cumulative_threats.threats) - pre_merge_count
                yield PipelineEvent(
                    step=PipelineStep.RULE_ENGINE,
                    status="completed",
                    message=(
                        f"Rule engine: {len(rule_threats.threats)} patterns matched, "
                        f"{added} new threats added after dedup"
                    ),
                    data={
                        "rule_engine_matched": len(rule_threats.threats),
                        "new_threats_added": added,
                        "total_threats": len(cumulative_threats.threats),
                    },
                )
            else:
                yield PipelineEvent(
                    step=PipelineStep.RULE_ENGINE,
                    status="completed",
                    message="Rule engine: no keyword matches found in description",
                    data={"rule_engine_matched": 0, "new_threats_added": 0},
                )

            # Dependency threats pass: deterministic threats derived from the
            # dependency capability analysis (source="dependency"), merged the
            # same way as rule-engine matches. Runs regardless of LLM success —
            # dependency findings are table-derived, not LLM output.
            if dependency_context is not None and dependency_context.packages:
                dep_threats = dependency_threats(
                    dependency_context, framework, scoring_method=self.config.scoring_method
                )
                if dep_threats.threats:
                    pre_merge_count = len(cumulative_threats.threats)
                    cumulative_threats = merge_dependency_threats(dep_threats, cumulative_threats)
                    added = len(cumulative_threats.threats) - pre_merge_count
                    yield PipelineEvent(
                        step=PipelineStep.ANALYZE_DEPENDENCIES,
                        status="completed",
                        message=(
                            f"Dependency threats: {len(dep_threats.threats)} findings, "
                            f"{added} new threats added after dedup"
                        ),
                        data={
                            "dependency_threats_matched": len(dep_threats.threats),
                            "new_threats_added": added,
                            "total_threats": len(cumulative_threats.threats),
                        },
                    )

            # Technique mapping pass: deterministic ATT&CK/ATLAS matching over
            # the final cumulative threat list. No LLM call, so it runs
            # regardless of LLM success and after every other merge so it
            # sees the complete set.
            yield PipelineEvent(
                step=PipelineStep.MAP_TECHNIQUES,
                status="started",
                message="Matching threats to ATT&CK/ATLAS techniques...",
            )
            # map_threat_techniques is synchronous CPU-bound work (embeds the
            # full technique catalog on first use, then each new threat) —
            # run it off the event loop so it can't block other requests,
            # SSE streams, or auth calls on this process while it runs.
            cumulative_threats, techniques_matched = await asyncio.to_thread(
                nodes.map_threat_techniques, cumulative_threats
            )
            yield PipelineEvent(
                step=PipelineStep.MAP_TECHNIQUES,
                status="completed",
                message=f"Technique mapping: {techniques_matched} technique matches across {len(cumulative_threats.threats)} threats",
                data={
                    "threats_mapped": len(cumulative_threats.threats),
                    "techniques_matched": techniques_matched,
                },
            )

            # Step 5: Complete
            total_duration = (datetime.now() - self.start_time).total_seconds()

            # fast_model is the identifier actually used for fast-routed steps,
            # or None when this run had no distinct fast provider (fast_model_share
            # would be meaningless in that case). build_run_usage() matches by
            # model *name* (it has no provider-object identity to compare), so
            # a same-named fast/main model here would wrongly report a 100%
            # share — checking .model, not just object identity, guards that
            # even though today's fast-provider builders already never
            # produce that pairing.
            fast_model = (
                self.fast_provider.model
                if self.fast_provider is not self.provider
                and self.fast_provider.model != self.provider.model
                else None
            )
            run_usage = build_run_usage(self._step_runs, fast_model=fast_model)
            run_usage.fast_routing_disabled = self._fast_disabled
            run_usage.refusal_count = self._refusal_count

            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="completed",
                message=f"Pipeline complete: {iterations_completed} iterations, {len(cumulative_threats.threats)} threats",
                data={
                    "iterations_completed": iterations_completed,
                    "total_threats": len(cumulative_threats.threats),
                    "duration_seconds": total_duration,
                    "stopped_reason": stopped_reason,
                    "threats": cumulative_threats,
                    "gaps": gaps,
                    "code_summary": code_summary,
                    "dependency_context": dependency_context,
                    "usage": run_usage.model_dump(),
                },
            )
            logger.info(
                "Pipeline complete: model=%s iterations=%d threats=%d stopped_reason=%s duration=%.1fs",
                self.model_id,
                iterations_completed,
                len(cumulative_threats.threats),
                stopped_reason,
                total_duration,
            )

        except Exception as e:
            yield PipelineEvent(
                step=PipelineStep.COMPLETE,
                status="failed",
                message=f"Pipeline failed: {e!s}",
                data={"error": str(e)},
            )
            raise

    async def generate_attack_tree_for_threat(
        self,
        threat_id: str,
        threat_name: str,
        threat_description: str,
        target: str,
        stride_category: str | None,
        maestro_category: str | None,
        mitigations: list[str],
    ) -> AttackTree:
        """Generate attack tree for a specific approved threat.

        Args:
            threat_id: Threat ID
            threat_name: Threat name
            threat_description: Threat description
            target: Target asset
            stride_category: Optional STRIDE category
            maestro_category: Optional MAESTRO category
            mitigations: Mitigations list

        Returns:
            AttackTree with Mermaid.js graph
        """
        result, _provider, _fallback_event = await self._call_step(
            PipelineStep.GENERATE_ATTACK_TREE,
            0,
            lambda p: nodes.generate_attack_tree(
                threat=threat_name,
                threat_description=threat_description,
                target=target,
                stride_category=stride_category,
                maestro_category=maestro_category,
                mitigations=mitigations,
                provider=p,
                temperature=0.3,  # Slightly higher for creativity
            ),
            {"threat_id": threat_id, "threat_name": threat_name},
        )
        return result

    async def generate_test_cases_for_threat(
        self,
        threat_id: str,
        threat_name: str,
        threat_description: str,
        target: str,
        mitigations: list[str],
    ) -> TestSuite:
        """Generate Gherkin test cases for a specific threat.

        Args:
            threat_id: Threat ID
            threat_name: Threat name
            threat_description: Threat description
            target: Target asset
            mitigations: Mitigations list

        Returns:
            TestSuite with Gherkin scenarios
        """
        result, _provider, _fallback_event = await self._call_step(
            PipelineStep.GENERATE_TEST_CASES,
            0,
            lambda p: nodes.generate_test_cases(
                threat=threat_name,
                threat_description=threat_description,
                target=target,
                mitigations=mitigations,
                provider=p,
                temperature=0.3,
            ),
            {"threat_id": threat_id, "threat_name": threat_name},
        )
        return result


async def run_pipeline_for_model(
    model_id: str,
    description: str,
    framework: Framework,
    provider: LLMProvider,
    architecture_diagram: str | None = None,
    assumptions: list[str] | None = None,
    code_context: CodeContext | None = None,
    diagrams: list[DiagramData] | None = None,
    max_iterations: int = 3,
    has_ai_components: bool = False,
    similarity_threshold: float = 0.85,
    stop_after: StopAfter | None = None,
    seeded_assets: AssetsList | None = None,
    seeded_flows: FlowsList | None = None,
    seeded_threats: ThreatsList | None = None,
    fast_provider: LLMProvider | None = None,
    temperature: float | None = None,
    seed_collections: list[str] | None = None,
    dependency_context: DependencyContext | None = None,
    dependency_manifest: dict | None = None,
    dependency_lockfile: dict | None = None,
    dependency_source_mode: str = "npm",
    persist_usage: bool = False,
    step_models: dict[PipelineStep, StepModelChoice] | None = None,
    scoring_method: ScoringMethod = "dread",
) -> AsyncGenerator[PipelineEvent, None]:
    """Convenience function to run pipeline for a threat model.

    Args:
        model_id: Threat model ID
        description: System description
        framework: STRIDE or MAESTRO
        provider: LLM provider for threat generation and gap analysis
        architecture_diagram: DEPRECATED - use diagrams instead
        assumptions: Optional assumptions
        code_context: Optional code context
        diagrams: Optional diagrams (PNG/JPG/Mermaid), 1 or more
        max_iterations: Maximum iteration count (1-15)
        has_ai_components: Whether to run MAESTRO alongside STRIDE
        similarity_threshold: Cosine similarity threshold for threat deduplication
        stop_after: Stop pipeline after "extraction" step (for context preview).
        seeded_assets: Pre-edited assets to skip LLM extraction.
        seeded_flows: Pre-edited flows to skip LLM extraction.
        seeded_threats: Known threats to seed the catalog before the iteration loop.
        fast_provider: Optional cheaper provider for extraction and enrichment steps.
            Falls back to ``provider`` when not set.
        temperature: LLM sampling temperature. Falls back to
            ``settings.default_temperature`` when not set.
        seed_collections: Seed collection names to restrict rule engine loading.
            None (default) uses settings.seed_collections, which defaults to all.
        dependency_context: Pre-analyzed dependency capabilities, used as-is.
        dependency_manifest: Parsed package.json to analyze when
            dependency_context isn't already provided.
        dependency_lockfile: Parsed package-lock.json (optional).
        dependency_source_mode: "npm" | "github" | "both" for dependency analysis.
        persist_usage: Write a pipeline_runs audit row per step. Only set
            this when `model_id` already names a saved threat_models row
            (true for the web run route) — see PipelineRunner's docstring.
        step_models: Per-step fast/main routing override. None (default)
            uses settings.step_models merged over the provider's default
            map (see PipelineRunner._step_models).
        scoring_method: "dread" | "cvss" | "both". Default "dread" — no
            behaviour change unless the caller passes the model's stored
            scoring_method (see Threat Model record).

    Yields:
        PipelineEvent for progress tracking
    """
    _clamped_max = max(1, min(15, max_iterations))
    step_models_override = step_models_override_from_settings(step_models, settings.step_models)
    config = PipelineConfig(
        max_iterations=_clamped_max,
        max_execution_time_minutes=settings.pipeline_timeout_minutes,
        temperature=temperature if temperature is not None else settings.default_temperature,
        enable_rag=True,
        has_ai_components=has_ai_components,
        similarity_threshold=similarity_threshold,
        dedup_saturation_threshold=settings.dedup_saturation_threshold,
        # Clamp min_iterations to [1, max_iterations] to prevent a floor that
        # can never be satisfied (e.g. MIN_ITERATIONS=5 with max_iterations=2).
        min_iterations=min(settings.min_iterations, _clamped_max),
        # Per-run override takes priority; fall back to global settings.
        # Empty list treated as None (all collections) to avoid silently
        # neutering the rule engine when the env var is unset.
        seed_collections=seed_collections
        if seed_collections is not None
        else (settings.seed_collections or None),
        step_models=step_models_override,
        scoring_method=scoring_method,
    )

    runner = PipelineRunner(
        provider=provider,
        config=config,
        model_id=model_id,
        fast_provider=fast_provider,
        persist_usage=persist_usage,
    )

    async for event in runner.run(
        description=description,
        framework=framework,
        architecture_diagram=architecture_diagram,
        assumptions=assumptions,
        code_context=code_context,
        diagrams=diagrams,
        stop_after=stop_after,
        seeded_assets=seeded_assets,
        seeded_flows=seeded_flows,
        seeded_threats=seeded_threats,
        dependency_context=dependency_context,
        dependency_manifest=dependency_manifest,
        dependency_lockfile=dependency_lockfile,
        dependency_source_mode=dependency_source_mode,
    ):
        yield event
