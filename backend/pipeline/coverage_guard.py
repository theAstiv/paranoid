"""Coverage guard: find categories with no LLM threats at the moment a run would stop.

Pure functions. The runner decides when to call them (see PipelineRunner.run);
nothing here touches a provider or the database.

A category is a hole at zero LLM threats, not at the "< 2" of the STRIDE balance
gate. Only source == "llm" counts: seeded threats are user input, and rule-engine /
dependency threats are not model output (they merge after the loop, so the
end-of-run report filters them out too).
"""

from collections import Counter
from dataclasses import dataclass, field

from backend.models.enums import MaestroCategory, StrideCategory
from backend.models.state import AssetsList, ThreatsList
from backend.models.usage import CoverageGuardReport
from backend.pipeline.nodes.maestro_tags import applicable_categories, tag_asset


_MAX_ASSETS_NAMED = 3


@dataclass(frozen=True)
class CoverageHoles:
    stride: list[StrideCategory] = field(default_factory=list)
    maestro: list[MaestroCategory] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.stride or self.maestro)

    @property
    def labels(self) -> list[str]:
        return [c.value for c in self.stride] + [f"MAESTRO: {c.value}" for c in self.maestro]


def applicable_maestro(assets: AssetsList | None) -> list[MaestroCategory]:
    if assets is None:
        return []
    return applicable_categories((a.name, a.description) for a in assets.assets)


def empty_categories(
    threats: ThreatsList,
    *,
    check_maestro: bool,
    applicable: list[MaestroCategory],
) -> CoverageHoles:
    """STRIDE categories, and applicable MAESTRO categories, with zero LLM threats.

    An empty `applicable` means no asset matched a rule, which is "unknown", so
    it never produces MAESTRO holes.
    """
    llm = [t for t in threats.threats if t.source == "llm"]
    stride_counts = Counter(t.stride_category for t in llm)
    maestro_counts = Counter(t.maestro_category for t in llm if t.maestro_category)
    maestro = [c for c in applicable if maestro_counts.get(c, 0) == 0] if check_maestro else []
    return CoverageHoles(
        stride=[c for c in StrideCategory if stride_counts.get(c, 0) == 0],
        maestro=maestro,
    )


def build_targeted_gap(holes: CoverageHoles, assets: AssetsList | None) -> str:
    """Gap text for the one extra pass. Names every hole; no model call."""
    parts: list[str] = []
    if holes.stride:
        names = ", ".join(c.value for c in holes.stride)
        parts.append(
            f"Coverage check: no STRIDE threats exist yet for {names}. "
            "Generate threats for each of these categories against the components in scope."
        )
    for category in holes.maestro:
        named = [
            a.name
            for a in (assets.assets if assets else [])
            if category in tag_asset(a.name, a.description)
        ][:_MAX_ASSETS_NAMED]
        where = f" (components: {', '.join(named)})" if named else ""
        parts.append(
            f"Coverage check: no MAESTRO threats exist yet for {category.value}{where}. "
            "Generate threats for this category."
        )
    parts.append("Do not repeat existing threats.")
    return " ".join(parts)


def plan_targeted_pass(
    threats: ThreatsList,
    assets: AssetsList | None,
    *,
    check_maestro: bool,
    applicable: list[MaestroCategory],
) -> tuple[list[str], str] | None:
    """(hole labels, gap text) when a stop should be overridden, else None."""
    holes = empty_categories(threats, check_maestro=check_maestro, applicable=applicable)
    if not holes:
        return None
    return holes.labels, build_targeted_gap(holes, assets)


def build_report(
    *,
    final_threats: ThreatsList,
    check_maestro: bool,
    applicable: list[MaestroCategory],
    triggered: bool,
    iteration: int | None,
    targeted: list[str],
) -> CoverageGuardReport | None:
    """End-of-run report; None when there is nothing to say."""
    holes = empty_categories(final_threats, check_maestro=check_maestro, applicable=applicable)
    na = (
        [c.value for c in MaestroCategory if c not in applicable]
        if check_maestro and applicable
        else []
    )
    unknown = check_maestro and not applicable
    if not (triggered or holes or na or unknown):
        return None
    return CoverageGuardReport(
        triggered=triggered,
        iteration=iteration,
        targeted=targeted,
        still_empty=holes.labels,
        na_maestro=na,
        unknown_maestro=unknown,
    )
