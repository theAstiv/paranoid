"""Pipeline orchestrator with iteration logic and SSE event streaming.

The runner coordinates all pipeline nodes, manages the iteration loop,
and emits server-sent events for real-time progress tracking.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import AsyncGenerator, Optional

from backend.dedup import deduplicate_threats
from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeContext, CodeSummary, TestSuite
from backend.models.state import AssetsList, FlowsList, SummaryState, ThreatsList
from backend.pipeline import nodes
from backend.providers.base import LLMProvider
from backend.serialization import serialize_event_data


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
    COMPLETE = "complete"


@dataclass
class PipelineEvent:
    """SSE event for pipeline progress."""

    step: PipelineStep
    status: str  # "started" | "completed" | "failed" | "info"
    message: str
    iteration: Optional[int] = None
    data: Optional[dict] = None
    timestamp: Optional[float] = None

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
    stopped_reason: str  # "max_iterations" | "gap_satisfied" | "timeout"


class PipelineRunner:
    """Orchestrates the threat modeling pipeline with iteration support."""

    def __init__(
        self,
        provider: LLMProvider,
        config: PipelineConfig,
        model_id: str,
    ):
        """Initialize pipeline runner.

        Args:
            provider: LLM provider for all generation steps
            config: Pipeline configuration
            model_id: Threat model ID for tracking
        """
        self.provider = provider
        self.config = config
        self.model_id = model_id
        self.start_time: Optional[datetime] = None

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
        architecture_diagram: Optional[str] = None,
        assumptions: Optional[list[str]] = None,
        code_context: Optional[CodeContext] = None,
    ) -> AsyncGenerator[PipelineEvent, None]:
        """Run the complete threat modeling pipeline with SSE events.

        Args:
            description: System description
            framework: STRIDE or MAESTRO framework
            architecture_diagram: Optional architecture diagram
            assumptions: Optional list of assumptions
            code_context: Optional code context from MCP

        Yields:
            PipelineEvent for each step and iteration
        """
        self.start_time = datetime.now()

        try:
            # Step 1: Summarize (+ code summarization if code context provided)
            yield PipelineEvent(
                step=PipelineStep.SUMMARIZE,
                status="started",
                message="Generating system summary...",
            )

            # Run summarize() and summarize_code() concurrently if code available
            if code_context:
                summary, code_summary = await asyncio.gather(
                    nodes.summarize(
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        code_context=code_context,
                        provider=self.provider,
                        temperature=self.config.temperature,
                    ),
                    nodes.summarize_code(
                        code_context=code_context,
                        provider=self.provider,
                        temperature=self.config.temperature,
                    ),
                )

                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE,
                    status="completed",
                    message=f"Summary generated: {len(summary.summary)} chars",
                    data={"summary": summary.summary},
                )

                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE_CODE,
                    status="completed",
                    message=f"Code summary: {len(code_summary.tech_stack)} technologies, {len(code_summary.entry_points)} entry points",
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
                    temperature=self.config.temperature,
                )
                code_summary = None

                yield PipelineEvent(
                    step=PipelineStep.SUMMARIZE,
                    status="completed",
                    message=f"Summary generated: {len(summary.summary)} chars",
                    data={"summary": summary.summary},
                )

            # Step 2: Extract Assets
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
                provider=self.provider,
                temperature=self.config.temperature,
                code_summary=code_summary,
            )

            yield PipelineEvent(
                step=PipelineStep.EXTRACT_ASSETS,
                status="completed",
                message=f"Identified {len(assets.assets)} assets/entities",
                data={"asset_count": len(assets.assets), "assets": assets},
            )

            # Step 3: Extract Flows
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
                provider=self.provider,
                temperature=self.config.temperature,
                code_summary=code_summary,
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

            # Step 4: Iterative Threat Generation
            # Iteration semantics:
            # - Each iteration generates NEW threats (not existing + new)
            # - The "improve" prompt asks LLM to find threats that were missed
            # - current_threats = latest iteration's output (NEW threats only)
            # - cumulative_threats = all threats from all iterations
            # - existing_threats passed to LLM = cumulative from previous iterations
            # - Gap analysis uses cumulative to assess full coverage
            current_threats: Optional[ThreatsList] = None
            cumulative_threats = ThreatsList(threats=[])  # Track all threats across iterations
            iteration = 1
            iterations_completed = 0  # Track completed iterations (avoids off-by-one on early exit)
            stopped_reason = "max_iterations"
            gaps: list[str] = []

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

                    # TODO: Phase 6.9 - Integrate RAG retrieval here
                    rag_context = None  # Will be populated in Phase 6.9

                    # Generate STRIDE threats
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
                    )

                    yield PipelineEvent(
                        step=PipelineStep.GENERATE_THREATS,
                        status="completed",
                        message=f"Generated {len(stride_threats.threats)} STRIDE threats",
                        iteration=iteration,
                        data={"threat_count": len(stride_threats.threats), "framework": "STRIDE", "threats": stride_threats},
                    )

                    # Generate MAESTRO threats for AI/ML components
                    yield PipelineEvent(
                        step=PipelineStep.GENERATE_THREATS,
                        status="started",
                        message=f"Generating MAESTRO threats for AI/ML components (iteration {iteration}/{self.config.max_iterations})...",
                        iteration=iteration,
                    )

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
                    )

                    yield PipelineEvent(
                        step=PipelineStep.GENERATE_THREATS,
                        status="completed",
                        message=f"Generated {len(maestro_threats.threats)} MAESTRO threats",
                        iteration=iteration,
                        data={"threat_count": len(maestro_threats.threats), "framework": "MAESTRO", "threats": maestro_threats},
                    )

                    # Merge and deduplicate across frameworks
                    combined = stride_threats + maestro_threats
                    dedup_result = deduplicate_threats(
                        combined, threshold=self.config.similarity_threshold,
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
                        data={"threat_count": len(current_threats.threats), "threats": current_threats, "framework": "COMBINED"},
                    )
                else:
                    # Single framework execution
                    yield PipelineEvent(
                        step=PipelineStep.GENERATE_THREATS,
                        status="started",
                        message=f"Generating threats (iteration {iteration}/{self.config.max_iterations})...",
                        iteration=iteration,
                    )

                    # TODO: Phase 6.9 - Integrate RAG retrieval here
                    rag_context = None  # Will be populated in Phase 6.9

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
                    )

                    yield PipelineEvent(
                        step=PipelineStep.GENERATE_THREATS,
                        status="completed",
                        message=f"Generated {len(current_threats.threats)} new threats",
                        iteration=iteration,
                        data={"threat_count": len(current_threats.threats), "threats": current_threats},
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
                    yield PipelineEvent(
                        step=PipelineStep.GAP_ANALYSIS,
                        status="started",
                        message="Analyzing threat coverage gaps...",
                        iteration=iteration,
                    )

                    gap_result = await nodes.gap_analysis(
                        description=description,
                        architecture_diagram=architecture_diagram,
                        assumptions=assumptions,
                        assets=assets,
                        flows=flows,
                        threats=cumulative_threats,
                        framework=framework,
                        provider=self.provider,
                        previous_gaps=gaps,
                        temperature=self.config.temperature,
                        code_summary=code_summary,
                    )

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
                message=f"Pipeline failed: {str(e)}",
                data={"error": str(e)},
            )
            raise

    async def generate_attack_tree_for_threat(
        self,
        threat_id: str,
        threat_name: str,
        threat_description: str,
        target: str,
        stride_category: Optional[str],
        maestro_category: Optional[str],
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
            provider=self.provider,
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
            provider=self.provider,
            temperature=0.3,
        )


async def run_pipeline_for_model(
    model_id: str,
    description: str,
    framework: Framework,
    provider: LLMProvider,
    architecture_diagram: Optional[str] = None,
    assumptions: Optional[list[str]] = None,
    code_context: Optional[CodeContext] = None,
    max_iterations: int = 3,
    has_ai_components: bool = False,
    similarity_threshold: float = 0.85,
) -> AsyncGenerator[PipelineEvent, None]:
    """Convenience function to run pipeline for a threat model.

    Args:
        model_id: Threat model ID
        description: System description
        framework: STRIDE or MAESTRO
        provider: LLM provider
        architecture_diagram: Optional diagram
        assumptions: Optional assumptions
        code_context: Optional code context
        max_iterations: Maximum iteration count (1-15)
        has_ai_components: Whether to run MAESTRO alongside STRIDE
        similarity_threshold: Cosine similarity threshold for threat deduplication

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
    )

    async for event in runner.run(
        description=description,
        framework=framework,
        architecture_diagram=architecture_diagram,
        assumptions=assumptions,
        code_context=code_context,
    ):
        yield event
