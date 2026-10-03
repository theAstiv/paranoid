"""Token-usage capture for LLM calls, without changing the provider protocol.

Providers call ``record_usage()`` after every API response — including the
extra attempts of an auto-bump retry, which are billed like any other call.
The pipeline runner opens a ``collect_usage()`` scope around each step and
reads what was recorded. Outside any scope, recording is a no-op, so
providers used directly (pre-flight checks, health checks) are unaffected.

A contextvar holding a *mutable* list carries the scope: recording happens in
the provider's async method (after the executor call returns, not inside the
worker thread), and a task created inside the scope copies the context but
still appends to the same list.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from backend.models.usage import ModelUsage, RunUsage, StepRun, UsageRecord


_collector: ContextVar[list[UsageRecord] | None] = ContextVar("llm_usage_collector", default=None)


def as_token_count(value: object) -> int:
    """Coerce a provider-reported count to an int; anything missing or non-numeric is 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0


def record_usage(record: UsageRecord) -> None:
    """Add one API response's usage to the innermost open scope, if any."""
    records = _collector.get()
    if records is not None:
        records.append(record)


@contextmanager
def collect_usage() -> Iterator[list[UsageRecord]]:
    """Collect every ``record_usage()`` made inside the block into the yielded list.

    Must not span a ``yield`` of an async generator: the contextvar is set and
    reset in the caller's context, so open the scope around a single await.
    """
    records: list[UsageRecord] = []
    token = _collector.set(records)
    try:
        yield records
    finally:
        _collector.reset(token)


def summarize_usage(records: Iterable[UsageRecord | ModelUsage]) -> list[ModelUsage]:
    """Sum usage per (provider, model), in first-seen order.

    Accepts raw per-call records or already-summed ``ModelUsage`` rows (a
    record counts as one call), so step totals roll up into run totals.
    """
    totals: dict[tuple[str, str], ModelUsage] = {}
    for item in records:
        key = (item.provider, item.model)
        row = totals.setdefault(key, ModelUsage(provider=item.provider, model=item.model))
        row.calls += item.calls if isinstance(item, ModelUsage) else 1
        row.input_tokens += item.input_tokens
        row.output_tokens += item.output_tokens
        row.cache_read_tokens += item.cache_read_tokens
        row.cache_write_tokens += item.cache_write_tokens
        row.total_tokens = (
            row.input_tokens + row.output_tokens + row.cache_read_tokens + row.cache_write_tokens
        )
    return list(totals.values())


def build_run_usage(steps: list[StepRun], fast_model: str | None = None) -> RunUsage:
    """Roll per-step usage up into a run report.

    Args:
        steps: Every step run so far, in execution order (failed ones included —
            their calls were made and billed).
        fast_model: The fast model's identifier, or None when the run had no
            fast model distinct from the main one.
    """
    by_model = summarize_usage(u for step in steps for u in step.usage)
    total = sum(m.total_tokens for m in by_model)
    if fast_model is None:
        return RunUsage(steps=steps, by_model=by_model, total_tokens=total)
    fast_tokens = sum(m.total_tokens for m in by_model if m.model == fast_model)
    return RunUsage(
        steps=steps,
        by_model=by_model,
        total_tokens=total,
        fast_model=fast_model,
        fast_model_tokens=fast_tokens,
        fast_model_share=round(fast_tokens / total, 4) if total else None,
    )
