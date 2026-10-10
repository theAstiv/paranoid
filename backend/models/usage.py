"""Pydantic models for LLM token-usage accounting (per call, per step, per run).

Tokens only — no prices. Providers report token counts; turning them into money
is left to the user's own provider logs and contract, since a price table in an
open-source tool goes stale and shows authoritative-looking wrong numbers.
"""

from typing import Literal

from pydantic import BaseModel


class UsageRecord(BaseModel):
    """Tokens reported by one provider API response, normalized across providers.

    The four counts never overlap: ``input_tokens`` is *uncached* input
    (Anthropic's meaning). Providers that fold cached tokens into their prompt
    count (OpenAI) have them moved to ``cache_read_tokens`` instead.
    """

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelUsage(BaseModel):
    """Usage summed over every call one (provider, model) pair served."""

    provider: str
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0


class StepRun(BaseModel):
    """One execution of an LLM-backed pipeline step: who served it and what it cost.

    ``usage`` has one entry per model that answered a call during the step —
    normally exactly one; empty when the step failed before any response.
    """

    step: str
    iteration: int  # 0 for the pre-loop steps (summarize, extraction)
    status: Literal["completed", "failed"]
    provider: str
    model: str  # model the step was routed to
    duration_ms: int
    input_hash: str
    output_hash: str  # "" when the step failed
    usage: list[ModelUsage]


class RunUsage(BaseModel):
    """Usage report for a whole pipeline run.

    ``fast_model`` is None when the run had no distinct fast model, in which
    case ``fast_model_share`` is None too (the share would be meaningless).
    """

    steps: list[StepRun]
    by_model: list[ModelUsage]
    total_tokens: int
    fast_model: str | None = None
    fast_model_tokens: int = 0
    fast_model_share: float | None = None
    # True when a non-transient fast-model failure tripped the circuit
    # breaker, so later fast-routed steps ran on main — such a run's token
    # split doesn't represent the configured routing.
    fast_routing_disabled: bool = False
    # Number of ProviderRefusalError occurrences during the run (a model or
    # content filter declined to answer) — reported separately from other
    # provider failures since retrying the same prompt won't help.
    refusal_count: int = 0
