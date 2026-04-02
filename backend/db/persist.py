"""Pipeline result persistence — writes all artifacts from a run to SQLite.

Single entry point: persist_pipeline_result(). Designed to be non-fatal:
any DB error is logged as a warning and does not propagate to the caller.
"""

import logging

from backend.db.crud import (
    create_asset,
    create_flow,
    create_threat,
    create_threat_model,
    create_threat_source,
    update_threat_model_status,
)
from backend.models.enums import Framework
from backend.models.state import AssetsList, FlowsList, ThreatsList


logger = logging.getLogger(__name__)


async def persist_pipeline_result(
    title: str,
    description: str,
    provider: str,
    model_name: str,
    framework: Framework,
    iterations_completed: int,
    assets: AssetsList | None,
    flows: FlowsList | None,
    threats: ThreatsList | None,
) -> str | None:
    """Persist all pipeline artifacts from a run to SQLite.

    Writes in dependency order: threat_model → assets → flows →
    trust_boundaries → threat_sources → threats. Sets model status
    to "completed" on success.

    Non-fatal: any exception is caught and logged — the caller always
    receives either a model_id string or None on failure.

    Args:
        title: Short label for this model (e.g. input filename stem)
        description: Full system description text
        provider: LLM provider name ("anthropic" | "openai" | "ollama")
        model_name: Model identifier string
        framework: STRIDE or MAESTRO
        iterations_completed: Number of pipeline iterations that ran
        assets: Extracted assets, or None if extraction failed
        flows: Extracted flows and trust boundaries, or None
        threats: Final merged threat list, or None

    Returns:
        model_id string on success, None on failure
    """
    try:
        model_id = await _persist(
            title=title,
            description=description,
            provider=provider,
            model_name=model_name,
            framework=framework,
            iterations_completed=iterations_completed,
            assets=assets,
            flows=flows,
            threats=threats,
        )
        logger.info(f"Persisted pipeline result: model_id={model_id}")
        return model_id
    except Exception as e:
        logger.warning(f"Failed to persist pipeline result (non-fatal): {e}")
        return None


async def _persist(
    title: str,
    description: str,
    provider: str,
    model_name: str,
    framework: Framework,
    iterations_completed: int,
    assets: AssetsList | None,
    flows: FlowsList | None,
    threats: ThreatsList | None,
) -> str:
    """Internal persistence logic — raises on failure."""
    model_id = await create_threat_model(
        title=title,
        description=description,
        provider=provider,
        model=model_name,
        framework=framework.value,
        iteration_count=iterations_completed,
    )

    if assets:
        for asset in assets.assets:
            await create_asset(
                model_id=model_id,
                asset_type=asset.type.value,
                name=asset.name,
                description=asset.description,
            )
        logger.debug(f"Persisted {len(assets.assets)} assets")

    if flows:
        for flow in flows.data_flows:
            await create_flow(
                model_id=model_id,
                flow_type="data_flow",
                flow_description=flow.flow_description,
                source_entity=flow.source_entity,
                target_entity=flow.target_entity,
            )

        for boundary in flows.trust_boundaries:
            await create_flow(
                model_id=model_id,
                flow_type="trust_boundary",
                flow_description=boundary.purpose,
                source_entity=boundary.source_entity,
                target_entity=boundary.target_entity,
            )

        for source in flows.threat_sources:
            await create_threat_source(
                model_id=model_id,
                category=source.category,
                description=source.description,
                example=source.example,
            )

        logger.debug(
            f"Persisted {len(flows.data_flows)} flows, "
            f"{len(flows.trust_boundaries)} trust boundaries, "
            f"{len(flows.threat_sources)} threat sources"
        )

    if threats:
        for threat in threats.threats:
            dread_damage = None
            dread_reproducibility = None
            dread_exploitability = None
            dread_affected_users = None
            dread_discoverability = None
            dread_score = None

            if threat.dread:
                dread_damage = threat.dread.damage
                dread_reproducibility = threat.dread.reproducibility
                dread_exploitability = threat.dread.exploitability
                dread_affected_users = threat.dread.affected_users
                dread_discoverability = threat.dread.discoverability
                dread_score = threat.dread.score

            await create_threat(
                model_id=model_id,
                name=threat.name,
                description=threat.description,
                target=threat.target,
                impact=threat.impact,
                likelihood=threat.likelihood,
                mitigations=threat.mitigations,
                stride_category=threat.stride_category.value if threat.stride_category else None,
                dread_score=dread_score,
                dread_damage=dread_damage,
                dread_reproducibility=dread_reproducibility,
                dread_exploitability=dread_exploitability,
                dread_affected_users=dread_affected_users,
                dread_discoverability=dread_discoverability,
            )

        logger.debug(f"Persisted {len(threats.threats)} threats")

    await update_threat_model_status(model_id, "completed")
    return model_id
