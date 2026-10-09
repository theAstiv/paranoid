"""Pre-run token and cost estimates (for `plan` and the budget guard).

Footprints come from measured runs on the demo fixture (Sonnet 5 / Haiku 4.5,
2026-10-05 routing runs and the 2026-10-08 multi-diagram runs). Bedrock has no
prompt-cache discount in Paranoid's provider today, so cached tokens are priced
as plain input here. Real runs vary by +-50% with the model and the iteration
count the pipeline actually completes; the estimate adds a 25% margin and is a
planning number, never a reported result.
"""

from decimal import Decimal

from pydantic import BaseModel

from tests.bench.matrix import Arm, Suite
from tests.bench.prices import MILLION, PriceTable


MARGIN = Decimal("1.25")

# (input, output) tokens.
PRE_FLIGHT = (1_900, 1_000)
EXTRACTION = {  # summarize + extract_assets + extract_flows
    "full": (11_900, 3_700),
    "diagrams_only": (11_500, 3_600),
    "full_no_diagrams": (7_900, 3_400),
    "maestro": (9_000, 3_600),
}
PER_ITERATION = (15_000, 6_000)  # generate_threats + gap_analysis, cache billed as input
ENRICH_PER_THREAT = (4_000, 3_000)  # attack tree + test cases
THREATS_PER_RUN = 28


class ArmEstimate(BaseModel):
    arm: str
    runs: int
    input_tokens: int
    output_tokens: int
    cost: Decimal | None  # for all of this arm's runs, with margin; None = unpriced


def _tokens(arm: Arm) -> tuple[tuple[int, int], tuple[int, int]]:
    """(main-model tokens, fast-model tokens) for one run of this arm."""
    ex_in, ex_out = EXTRACTION[arm.inputs]
    main_in = PRE_FLIGHT[0] + arm.iterations * PER_ITERATION[0]
    main_out = PRE_FLIGHT[1] + arm.iterations * PER_ITERATION[1]
    # summarize stays on main; the two extract steps go to fast unless routed to main.
    summarize_share = Decimal("0.15")
    sum_in, sum_out = int(ex_in * summarize_share), int(ex_out * summarize_share)
    rest_in, rest_out = ex_in - sum_in, ex_out - sum_out
    main_in, main_out = main_in + sum_in, main_out + sum_out
    fast_in = fast_out = 0
    extraction_on_main = arm.fast is None or arm.step_models.get("extract_flows") == "main"
    if extraction_on_main:
        main_in, main_out = main_in + rest_in, main_out + rest_out
    else:
        fast_in, fast_out = rest_in, rest_out
    if arm.enrich:
        e_in, e_out = ENRICH_PER_THREAT[0] * THREATS_PER_RUN, ENRICH_PER_THREAT[1] * THREATS_PER_RUN
        if arm.fast is None:
            main_in, main_out = main_in + e_in, main_out + e_out
        else:
            fast_in, fast_out = fast_in + e_in, fast_out + e_out
    return (main_in, main_out), (fast_in, fast_out)


def _price_for(slot: str | None, prices: PriceTable | None):
    return prices.models.get(slot) if (prices and slot) else None


def estimate_arm(arm: Arm, reps: int, prices: PriceTable | None) -> ArmEstimate:
    if arm.main is None:
        return ArmEstimate(arm=arm.id, runs=reps, input_tokens=0, output_tokens=0, cost=Decimal(0))
    (m_in, m_out), (f_in, f_out) = _tokens(arm)
    main_price = _price_for(arm.main.slot, prices)
    fast_price = _price_for((arm.fast or arm.main).slot, prices)
    cost = None
    if main_price is not None and (fast_price is not None or (f_in == 0 and f_out == 0)):
        per_run = (Decimal(m_in) * main_price.input + Decimal(m_out) * main_price.output) / MILLION
        if fast_price is not None:
            per_run += (
                Decimal(f_in) * fast_price.input + Decimal(f_out) * fast_price.output
            ) / MILLION
        cost = (per_run * reps * arm.pipeline_runs_per_rep * MARGIN).quantize(Decimal("0.01"))
    runs = reps * arm.pipeline_runs_per_rep
    return ArmEstimate(
        arm=arm.id,
        runs=runs,
        input_tokens=(m_in + f_in) * runs,
        output_tokens=(m_out + f_out) * runs,
        cost=cost,
    )


def estimate_suite(
    suite: Suite, prices: PriceTable | None, reps: int | None = None
) -> list[ArmEstimate]:
    return [estimate_arm(arm, reps or suite.reps, prices) for arm in suite.arms]


def per_run_estimate(arm: Arm, prices: PriceTable | None) -> Decimal | None:
    return estimate_arm(arm, 1, prices).cost
