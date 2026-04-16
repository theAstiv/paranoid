"""Pipeline orchestrator with iteration logic and SSE event streaming.

The runner coordinates all pipeline nodes, manages the iteration loop,
and emits server-sent events for real-time progress tracking.
"""

import json
import time
from collections import Counter
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from backend.dedup import deduplicate_threats
from backend.models.enums import Framework, StrideCategory
from backend.models.extended import AttackTree, CodeContext, DiagramData, TestSuite
from backend.models.state import AssetsList, FlowsList, SummaryState, ThreatsList
from backend.pipeline import nodes
from backend.pipeline.nodes.helpers import build_shared_context
from backend.pipeline.nodes.summary import _deterministic_code_summary
from backend.providers.base import LLMProvider, ProviderError
from backend.rules.engine import fetch_rag_context, merge_rule_and_llm_threats, run_rule_engine
from backend.serialization import serialize_event_data


StopAfter = Literal["extraction"]


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
    COMPLETE = "complete"


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


@dataclass
class PipelineResult:
    """Final pipeline execution result."""

    summary: SummaryState
    assets: AssetsList
    flows: FlowsList
    threats: ThreatsList
    iterations_completed: int
    total_duration_seconds: float
    stopped_reason: str  # "max_iterations" | "gap_satisfied" | "timeout" | "provider_offline"


class PipelineRunner:
    """Orchestrates the threat modeling pipeline with iteration support."""

    def __init__(
        self,
        provider: LLMProvider,
        config: PipelineConfig,
        model_id: str,
        fast_provider: LLMProvider | None = None,
    ):
        """Initialize pipeline runner.

        Args:
            provider: LLM provider for threat generation, gap analysis, and summarization.
            config: Pipeline configuration.
            model_id: Threat model ID for tracking.
            fast_provider: Optional cheaper/faster provider for extraction steps
                (assets, flows) and enrichment (attack trees, test cases).
                Falls back to ``provider`` when not set.
        """
        self.provider = provider
        self.fast_provider = fast_provider or provider
        self.config = config
        self.model_id = model_id
        self.start_time: datetime | None = None

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
        diagram_data: DiagramData | None = None,
        stop_after: StopAfter | None = None,
        seeded_assets: AssetsList | None = None,
        seeded_flows: FlowsList | None = None,
    ) -> AsyncGenerator[PipelineEvent, None]:
        """Run the complete threat modeling pipeline with SSE events.

        Args:
            description: System description
            framework: STRIDE or MAESTRO framework
            architecture_diagram: DEPRECATED - use diagram_data instead
            assumptions: Optional list of assumptions
            code_context: Optional code context from MCP
            diagram_data: Optional diagram data (PNG/JPG/Mermaid)
            stop_after: If "extraction", stop after assets/flows are extracted and
                persisted, then yield a complete event. Used by the /extract endpoint
                to populate context without running threat generation.
            seeded_assets: Pre-edited assets to use instead of running LLM extraction.
                When provided the EXTRACT_ASSETS step is skipped.
            seeded_flows: Pre-edited flows/boundaries to use instead of running LLM
                extraction. When provided the EXTRACT_FLOWS step is skipped.

        Yields:
            PipelineEvent for each step and iteration
        """
        self.start_time = datetime.now()

        # Iteration state is initialized here (not inside the try) so that a
        # ProviderError in the pre-loop steps can still fall through to the rule
        # engine and complete event with sensible defaults.
        provider_failed = False
        current_threats: ThreatsList | None = None
        cumulative_threats = ThreatsList(threats=[])
        iteration = 1
        iterations_completed = 0
        stopped_reason = "max_iterations"
        gaps: list[str] = []
        code_summary = None
        shared_ctx: str | None = None

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
                    summary = await nodes.summarize(
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        code_context=code_context,
                        provider=self.provider,
                        diagram_data=diagram_data,
                        temperature=self.config.temperature,
                    )

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE,
                        status="completed",
                        message=f"Summary generated: {len(summary.summary)} chars",
                        data={"summary": summary.summary},
                    )

                    code_summary = _deterministic_code_summary(code_context)

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE_CODE,
                        status="completed",
                        message=f"Code analyzed: {len(code_summary.tech_stack)} technologies, {len(code_summary.entry_points)} entry points",
                        data={
                            "tech_stack": code_summary.tech_stack,
                            "entry_points": code_summary.entry_points,
                            "code_summary": code_summary,
                        },
                    )
                else:
                    summary = await nodes.summarize(
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        code_context=None,
                        provider=self.provider,
                        diagram_data=diagram_data,
                        temperature=self.config.temperature,
                    )
                    code_summary = None

                    yield PipelineEvent(
                        step=PipelineStep.SUMMARIZE,
                        status="completed",
                        message=f"Summary generated: {len(summary.summary)} chars",
                        data={"summary": summary.summary},
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

                    assets = await nodes.extract_assets(
                        summary=summary.summary,
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        framework=framework,
                        provider=self.fast_provider,
                        temperature=self.config.temperature,
                        code_summary=code_summary,
                        diagram_data=diagram_data,
                    )

                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_ASSETS,
                        status="completed",
                        message=f"Identified {len(assets.assets)} assets/entities",
                        data={"asset_count": len(assets.assets), "assets": assets},
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

                    flows = await nodes.extract_flows(
                        summary=summary.summary,
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        assets=assets,
                        provider=self.fast_provider,
                        temperature=self.config.temperature,
                        code_summary=code_summary,
                        diagram_data=diagram_data,
                    )

                    yield PipelineEvent(
                        step=PipelineStep.EXTRACT_FLOWS,
                        status="completed",
                        message=f"Identified {len(flows.data_flows)} flows, {len(flows.trust_boundaries)} boundaries",
                        data={
                            "flow_count": len(flows.data_flows),
                            "boundary_count": len(flows.trust_boundaries),
                            "flows": flows,
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
                    diagram_data=diagram_data,
                    framework=framework,
                )

            except ProviderError as e:
                # LLM provider is offline — degrade gracefully to rule-engine-only.
                # Use the original description as a minimal summary so the rule
                # engine still has text to match keywords against.
                provider_failed = True
                stopped_reason = "provider_offline"
                summary = SummaryState(summary=description)
                assets = AssetsList(assets=[])
                flows = FlowsList(data_flows=[], trust_boundaries=[], threat_sources=[])
                yield PipelineEvent(
                    step=PipelineStep.RULE_ENGINE,
                    status="info",
                    message=(
                        f"LLM provider unavailable ({e}) — switching to rule-engine-only mode"
                    ),
                    data={"error": str(e)},
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
                assets_text = " ".join(a.name for a in assets.assets)
                rag_context = await fetch_rag_context(description, assets_text=assets_text)
            else:
                rag_context = None

            if not provider_failed:
                while iteration <= self.config.max_iterations:
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
                            stride_threats = await nodes.generate_threats(
                                description=description,
                                architecture_diagram=architecture_diagram,
                                assumptions=assumptions,
                                assets=assets,
                                flows=flows,
                                framework=Framework.STRIDE,
                                provider=self.provider,
                                existing_threats=current_threats if iteration > 1 else None,
                                gap_analysis=gaps[-1] if gaps else None,
                                rag_context=rag_context,
                                temperature=self.config.temperature,
                                code_summary=code_summary,
                                diagram_data=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                shared_context=shared_ctx,
                            )
                        except ProviderError as e:
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data={"error": str(e)},
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
                            maestro_threats = await nodes.generate_threats(
                                description=description,
                                architecture_diagram=architecture_diagram,
                                assumptions=assumptions,
                                assets=assets,
                                flows=flows,
                                framework=Framework.MAESTRO,
                                provider=self.provider,
                                existing_threats=None,  # MAESTRO threats are separate
                                gap_analysis=gaps[-1] if gaps else None,
                                rag_context=rag_context,
                                temperature=self.config.temperature,
                                code_summary=code_summary,
                                diagram_data=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                shared_context=shared_ctx,
                            )
                        except ProviderError as e:
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            # Preserve STRIDE threats from this iteration before yielding
                            # so the event stream is monotonic (state updated, then announced).
                            cumulative_threats.threats.extend(stride_threats.threats)
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data={"error": str(e)},
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
                            current_threats = await nodes.generate_threats(
                                description=description,
                                architecture_diagram=architecture_diagram,
                                assumptions=assumptions,
                                assets=assets,
                                flows=flows,
                                framework=framework,
                                provider=self.provider,
                                existing_threats=current_threats if iteration > 1 else None,
                                gap_analysis=gaps[-1] if gaps else None,
                                rag_context=rag_context,
                                temperature=self.config.temperature,
                                code_summary=code_summary,
                                diagram_data=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                shared_context=shared_ctx,
                            )
                        except ProviderError as e:
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable after {iterations_completed} completed "
                                    f"iteration(s) ({e}) — switching to rule-engine-only mode"
                                ),
                                data={"error": str(e)},
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
                            },
                        )

                    # Deduplicate against cumulative threats from prior iterations
                    if iteration > 1:
                        dedup_result = deduplicate_threats(
                            current_threats,
                            existing_threats=cumulative_threats,
                            threshold=self.config.similarity_threshold,
                        )
                        cumulative_threats.threats.extend(dedup_result.threats.threats)
                        if dedup_result.removed_count > 0:
                            yield PipelineEvent(
                                step=PipelineStep.GENERATE_THREATS,
                                status="info",
                                message=f"Removed {dedup_result.removed_count} cross-iteration duplicates",
                                iteration=iteration,
                                data={"duplicates_removed": dedup_result.removed_count},
                            )
                    else:
                        cumulative_threats.threats.extend(current_threats.threats)
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
                        if framework == Framework.STRIDE and _is_stride_coverage_balanced(
                            cumulative_threats
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
                            gap_result = await nodes.gap_analysis(
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
                                diagram_data=None,  # vision image intentionally dropped on iteration calls — generate_threats and gap_analysis rely on the assets/flows extracted from the earlier vision passes
                                shared_context=shared_ctx,
                            )
                        except ProviderError as e:
                            provider_failed = True
                            stopped_reason = "provider_offline"
                            yield PipelineEvent(
                                step=PipelineStep.RULE_ENGINE,
                                status="info",
                                message=(
                                    f"LLM provider unavailable during gap analysis ({e}) — "
                                    "switching to rule-engine-only mode"
                                ),
                                data={"error": str(e)},
                            )
                            break

                        if gap_result.stop:
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message="Gap analysis satisfied - stopping iterations",
                                iteration=iteration,
                                data={"stop": True, "gap": gap_result.gap},
                            )
                            stopped_reason = "gap_satisfied"
                            break
                        else:
                            gaps.append(gap_result.gap)
                            yield PipelineEvent(
                                step=PipelineStep.GAP_ANALYSIS,
                                status="completed",
                                message=f"Gap identified: {gap_result.gap[:100]}...",
                                iteration=iteration,
                                data={"stop": False, "gap": gap_result.gap},
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

            rule_threats = run_rule_engine(description, framework)

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

            # Step 5: Complete
            total_duration = (datetime.now() - self.start_time).total_seconds()

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
                },
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
        return await nodes.generate_attack_tree(
            threat=threat_name,
            threat_description=threat_description,
            target=target,
            stride_category=stride_category,
            maestro_category=maestro_category,
            mitigations=mitigations,
            provider=self.fast_provider,
            temperature=0.3,  # Slightly higher for creativity
        )

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
        return await nodes.generate_test_cases(
            threat=threat_name,
            threat_description=threat_description,
            target=target,
            mitigations=mitigations,
            provider=self.fast_provider,
            temperature=0.3,
        )


async def run_pipeline_for_model(
    model_id: str,
    description: str,
    framework: Framework,
    provider: LLMProvider,
    architecture_diagram: str | None = None,
    assumptions: list[str] | None = None,
    code_context: CodeContext | None = None,
    diagram_data: DiagramData | None = None,
    max_iterations: int = 3,
    has_ai_components: bool = False,
    similarity_threshold: float = 0.85,
    stop_after: StopAfter | None = None,
    seeded_assets: AssetsList | None = None,
    seeded_flows: FlowsList | None = None,
    fast_provider: LLMProvider | None = None,
) -> AsyncGenerator[PipelineEvent, None]:
    """Convenience function to run pipeline for a threat model.

    Args:
        model_id: Threat model ID
        description: System description
        framework: STRIDE or MAESTRO
        provider: LLM provider for threat generation and gap analysis
        architecture_diagram: DEPRECATED - use diagram_data instead
        assumptions: Optional assumptions
        code_context: Optional code context
        diagram_data: Optional diagram data (PNG/JPG/Mermaid)
        max_iterations: Maximum iteration count (1-15)
        has_ai_components: Whether to run MAESTRO alongside STRIDE
        similarity_threshold: Cosine similarity threshold for threat deduplication
        stop_after: Stop pipeline after "extraction" step (for context preview).
        seeded_assets: Pre-edited assets to skip LLM extraction.
        seeded_flows: Pre-edited flows to skip LLM extraction.
        fast_provider: Optional cheaper provider for extraction and enrichment steps.
            Falls back to ``provider`` when not set.

    Yields:
        PipelineEvent for progress tracking
    """
    config = PipelineConfig(
        max_iterations=max(1, min(15, max_iterations)),  # Clamp to 1-15
        max_execution_time_minutes=30,
        temperature=0.2,
        enable_rag=True,
        has_ai_components=has_ai_components,
        similarity_threshold=similarity_threshold,
    )

    runner = PipelineRunner(
        provider=provider,
        config=config,
        model_id=model_id,
        fast_provider=fast_provider,
    )

    async for event in runner.run(
        description=description,
        framework=framework,
        architecture_diagram=architecture_diagram,
        assumptions=assumptions,
        code_context=code_context,
        diagram_data=diagram_data,
        stop_after=stop_after,
        seeded_assets=seeded_assets,
        seeded_flows=seeded_flows,
    ):
        yield event
