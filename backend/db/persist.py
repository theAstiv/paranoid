"""Pipeline result persistence — CLI path only.

This module is invoked by the CLI runner (cli/main.py) after a pipeline run
completes. It is NOT used by the API path: the FastAPI route in
backend/routes/models.py streams events via SSE and persists data
incrementally through _persist_pipeline_event() instead.

Single entry point: persist_pipeline_result(). Designed to be non-fatal:
any DB error is logged as a warning and does not propagate to the caller.
"""

import logging

from backend.db.crud import (
    create_asset,
    create_attack_tree,
    create_flow,
    create_test_case,
    create_threat,
    create_threat_model,
    create_threat_source,
    create_trust_boundary,
    update_threat_model_status,
)
from backend.models.enums import Framework
from backend.models.extended import AttackTree, TestSuite
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
    attack_trees: dict[str, AttackTree] | None = None,
    test_suites: dict[str, TestSuite] | None = None,
) -> str | None:
    """Persist all pipeline artifacts from a run to SQLite.

    Writes in dependency order: threat_model → assets → flows →
    trust_boundaries → threat_sources → threats → attack_trees → test_cases.
    Sets model status to "completed" on success.

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
        attack_trees: Map of synthetic threat index → AttackTree (from --enrich), or None
        test_suites: Map of synthetic threat index → TestSuite (from --enrich), or None

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
            attack_trees=attack_trees,
            test_suites=test_suites,
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
    attack_trees: dict[str, AttackTree] | None = None,
    test_suites: dict[str, TestSuite] | None = None,
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
                flow_type="data",
                flow_description=flow.flow_description,
                source_entity=flow.source_entity,
                target_entity=flow.target_entity,
            )

        for boundary in flows.trust_boundaries:
            await create_trust_boundary(
                model_id=model_id,
                purpose=boundary.purpose,
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

    # threat_db_ids maps synthetic index → real DB UUID so attack trees and
    # test suites (keyed by str(i)) can be saved against the correct threat.
    threat_db_ids: list[str] = []
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

            threat_db_id = await create_threat(
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
            threat_db_ids.append(threat_db_id)

        logger.debug(f"Persisted {len(threats.threats)} threats")

    if attack_trees and threat_db_ids:
        saved = 0
        for idx_str, tree in attack_trees.items():
            idx = int(idx_str)
            if idx < len(threat_db_ids):
                await create_attack_tree(
                    threat_id=threat_db_ids[idx],
                    mermaid_source=tree.mermaid_source,
                )
                saved += 1
        logger.debug(f"Persisted {saved} attack trees")

    if test_suites and threat_db_ids:
        saved = 0
        for idx_str, suite in test_suites.items():
            idx = int(idx_str)
            if idx < len(threat_db_ids):
                await create_test_case(
                    threat_id=threat_db_ids[idx],
                    gherkin_source=suite.gherkin_source,
                )
                saved += 1
        logger.debug(f"Persisted {saved} test cases")

    await update_threat_model_status(model_id, "completed")
    return model_id
