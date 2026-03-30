"""Mock LLM provider for testing pipeline without API tokens.

Satisfies LLMProvider protocol. Routes generate_structured() calls
to pre-built response fixtures based on response_model type.
Framework dispatch is explicit via constructor — no prompt string matching.
"""

from typing import Any

from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeSummary, TestSuite
from backend.models.state import (
    AssetsList,
    FlowsList,
    GapAnalysis,
    SummaryState,
    ThreatsList,
)
from backend.providers.base import ProviderError
from tests.fixtures.pipeline import (
    make_assets,
    make_attack_tree,
    make_code_summary,
    make_flows,
    make_gap_analysis,
    make_gap_analysis_stop,
    make_maestro_threats,
    make_stride_threats,
    make_summary,
    make_test_suite,
)


class MockProvider:
    """In-process mock implementing LLMProvider protocol.

    Args:
        framework: Controls ThreatsList dispatch (STRIDE vs MAESTRO).
        gap_call_threshold: After this many GapAnalysis calls, return stop=True.
    """

    def __init__(
        self,
        framework: Framework = Framework.STRIDE,
        gap_call_threshold: int = 2,
    ) -> None:
        self._framework = framework
        self._gap_call_threshold = gap_call_threshold
        self.calls: list[dict[str, Any]] = []
        self.response_overrides: dict[type, Any] = {}
        self.error_types: set[type] = set()
        self._gap_call_count = 0
        self.last_prompt: str | None = None
        self.last_images: list | None = None

    @property
    def name(self) -> str:
        return "mock"

    @property
    def model(self) -> str:
        return "mock-v1"

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[Any],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        images: list | None = None,
    ) -> Any:
        # Capture for diagram tests
        self.last_prompt = prompt
        self.last_images = images

        self.calls.append(
            {
                "method": "generate_structured",
                "response_model": response_model,
                "temperature": temperature,
                "prompt_length": len(prompt),
                "images": images,
            }
        )

        if response_model in self.error_types:
            raise ProviderError(
                provider="mock",
                message=f"Mock error for {response_model.__name__}",
            )

        if response_model in self.response_overrides:
            return self.response_overrides[response_model]

        return self._dispatch(response_model)

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "method": "generate",
                "temperature": temperature,
                "prompt_length": len(prompt),
            }
        )
        return "Mock response for testing."

    async def __aenter__(self) -> "MockProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def _dispatch(self, response_model: type[Any]) -> Any:
        """Route response_model type to the appropriate fixture factory."""
        dispatch_table: dict[type, Any] = {
            SummaryState: make_summary,
            AssetsList: make_assets,
            FlowsList: make_flows,
            CodeSummary: make_code_summary,
            AttackTree: make_attack_tree,
            TestSuite: make_test_suite,
        }

        if response_model in dispatch_table:
            return dispatch_table[response_model]()

        if response_model is ThreatsList:
            if self._framework == Framework.MAESTRO:
                return make_maestro_threats()
            return make_stride_threats()

        if response_model is GapAnalysis:
            self._gap_call_count += 1
            if self._gap_call_count >= self._gap_call_threshold:
                return make_gap_analysis_stop()
            return make_gap_analysis()

        raise ValueError(f"MockProvider has no fixture for {response_model.__name__}")
