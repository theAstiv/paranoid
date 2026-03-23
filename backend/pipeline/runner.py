"""Pipeline orchestrator with iteration logic and SSE event streaming.

The runner coordinates all pipeline nodes, manages the iteration loop,
and emits server-sent events for real-time progress tracking.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import AsyncGenerator, Optional

from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeContext, TestSuite
from backend.models.state import AssetsList, FlowsList, SummaryState, ThreatsList
from backend.pipeline import nodes
from backend.providers.base import LLMProvider


class PipelineStep(str, Enum):
    """Pipeline step identifiers for SSE events."""

    SUMMARIZE = "summarize"
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
        """Convert to SSE format string."""
        import json

        event_data = {
            "step": self.step.value if isinstance(self.step, PipelineStep) else self.step,
            "status": self.status,
            "message": self.message,
            "iteration": self.iteration,
            "data": self.data,
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
            # Step 1: Summarize
            yield PipelineEvent(
                step=PipelineStep.SUMMARIZE,
                status="started",
                message="Generating system summary...",
            )

            summary = await nodes.summarize(
                description=description,
                architecture_diagram=architecture_diagram,
                assumptions=assumptions,
                code_context=code_context,
                provider=self.provider,
                temperature=self.config.temperature,
            )

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
            )

            yield PipelineEvent(
                step=PipelineStep.EXTRACT_ASSETS,
                status="completed",
                message=f"Identified {len(assets.assets_list)} assets/entities",
                data={"asset_count": len(assets.assets_list)},
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
            )

            yield PipelineEvent(
                step=PipelineStep.EXTRACT_FLOWS,
                status="completed",
                message=f"Identified {len(flows.data_flows)} flows, {len(flows.trust_boundaries)} boundaries",
                data={
                    "flow_count": len(flows.data_flows),
                    "boundary_count": len(flows.trust_boundaries),
                },
            )

            # Step 4: Iterative Threat Generation
            current_threats: Optional[ThreatsList] = None
            iteration = 1
            stopped_reason = "max_iterations"
            gaps: list[str] = []

            while iteration <= self.config.max_iterations:
                # Check time limit
                if self._check_time_limit():
                    yield PipelineEvent(
                        step=PipelineStep.ITERATE,
                        status="info",
                        message=f"Time limit reached after {iteration - 1} iterations",
                        iteration=iteration,
                    )
                    stopped_reason = "timeout"
                    break

                # Generate threats
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
                )

                yield PipelineEvent(
                    step=PipelineStep.GENERATE_THREATS,
                    status="completed",
                    message=f"Generated {len(current_threats.threat_list)} threats",
                    iteration=iteration,
                    data={"threat_count": len(current_threats.threat_list)},
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
                        threats=current_threats,
                        framework=framework,
                        provider=self.provider,
                        previous_gaps=gaps,
                        temperature=self.config.temperature,
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
                message=f"Pipeline complete: {iteration - 1} iterations, {len(current_threats.threat_list)} threats",
                data={
                    "iterations": iteration - 1,
                    "threat_count": len(current_threats.threat_list),
                    "duration_seconds": total_duration,
                    "stopped_reason": stopped_reason,
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

    Yields:
        PipelineEvent for progress tracking
    """
    config = PipelineConfig(
        max_iterations=max(1, min(15, max_iterations)),  # Clamp to 1-15
        max_execution_time_minutes=30,
        temperature=0.2,
        enable_rag=True,
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
