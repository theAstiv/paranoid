"""Price table (per million tokens, keyed by model slot) and cost arithmetic.

Prices are read by hand from the provider's pricing page on the day and stored in
the JSON file named by BENCH_PRICES_FILE (template: prices.example.json). An
unknown price yields None, never 0, so a missing row can't make a run look free.
"""

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel


MILLION = Decimal(1_000_000)


class Price(BaseModel):
    input: Decimal
    output: Decimal
    cache_read: Decimal = Decimal(0)
    cache_write: Decimal = Decimal(0)
    source: str
    read_on: str
    region: str | None = None


class PriceTable(BaseModel):
    currency: str = "USD"
    models: dict[str, Price]


def load_prices(path: Path | None) -> PriceTable | None:
    if path is None or not path.is_file():
        return None
    return PriceTable.model_validate(json.loads(path.read_text(encoding="utf-8")))


def usage_cost(usage: dict, price: Price) -> Decimal:
    """Cost of one usage record (the ModelUsage shape in backend/models/usage.py)."""
    return (
        Decimal(usage.get("input_tokens", 0)) * price.input
        + Decimal(usage.get("output_tokens", 0)) * price.output
        + Decimal(usage.get("cache_read_tokens", 0)) * price.cache_read
        + Decimal(usage.get("cache_write_tokens", 0)) * price.cache_write
    ) / MILLION


def run_cost(
    by_model: list[dict], model_to_slot: dict[str, str], prices: PriceTable | None
) -> Decimal | None:
    """Total cost of a run's `usage_summary.by_model`, or None if any model is unpriced."""
    if prices is None:
        return None
    total = Decimal(0)
    for usage in by_model:
        slot = model_to_slot.get(usage.get("model", ""))
        price = prices.models.get(slot) if slot else None
        if price is None:
            return None
        total += usage_cost(usage, price)
    return total


def step_costs(
    steps: list[dict], model_to_slot: dict[str, str], prices: PriceTable | None
) -> dict[str, Decimal | None]:
    """Cost per step name, summed over iterations (None for a step with an unpriced model)."""
    out: dict[str, Decimal | None] = {}
    for step in steps:
        name = step["step"]
        for usage in step.get("usage", []):
            slot = model_to_slot.get(usage.get("model", ""))
            price = prices.models.get(slot) if (prices and slot) else None
            if price is None:
                out[name] = None
                continue
            if name in out and out[name] is None:
                continue
            out[name] = (out.get(name) or Decimal(0)) + usage_cost(usage, price)
    return out
