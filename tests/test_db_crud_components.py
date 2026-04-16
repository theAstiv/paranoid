"""Tests for component-level CRUD operations.

Covers get/delete for assets, flows, trust_boundaries, threat_sources,
and full CRUD for attack_trees and test_cases.
"""

import pytest

from backend.db import crud


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_model() -> str:
    return await crud.create_threat_model(
        title="Component Test",
        description="desc",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=1,
    )


async def _make_threat(model_id: str) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name="SQL Injection",
        description="An attacker exploits unparameterized queries to read arbitrary data.",
        target="Database",
        impact="Data breach",
        likelihood="High",
        mitigations=["[P] Use parameterized queries"],
        stride_category="Tampering",
    )


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_asset_returns_correct_record(test_db) -> None:
    """get_asset retrieves the asset by ID."""
    model_id = await _make_model()
    asset_id = await crud.create_asset(
        model_id=model_id,
        asset_type="Asset",
        name="User Database",
        description="Stores user credentials",
    )

    asset = await crud.get_asset(asset_id)

    assert asset is not None
    assert asset["id"] == asset_id
    assert asset["name"] == "User Database"
    assert asset["type"] == "Asset"


@pytest.mark.asyncio
async def test_get_asset_returns_none_for_missing(test_db) -> None:
    """get_asset returns None for an unknown ID."""
    result = await crud.get_asset("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_delete_asset_removes_record(test_db) -> None:
    """delete_asset removes the asset; get_asset returns None afterwards."""
    model_id = await _make_model()
    asset_id = await crud.create_asset(
        model_id=model_id,
        asset_type="Entity",
        name="Admin Service",
        description="Internal service",
    )

    await crud.delete_asset(asset_id)

    assert await crud.get_asset(asset_id) is None


@pytest.mark.asyncio
async def test_delete_asset_does_not_remove_sibling_assets(test_db) -> None:
    """Deleting one asset leaves other assets for the same model intact."""
    model_id = await _make_model()
    id_a = await crud.create_asset(model_id, "Asset", "DB", "database")
    id_b = await crud.create_asset(model_id, "Entity", "API", "api service")

    await crud.delete_asset(id_a)

    remaining = await crud.list_assets(model_id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == id_b


@pytest.mark.asyncio
async def test_update_asset_changes_fields(test_db) -> None:
    """update_asset updates only the provided fields."""
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "Original Name", "Original desc")

    await crud.update_asset(asset_id, name="Updated Name", asset_type="Entity")

    asset = await crud.get_asset(asset_id)
    assert asset["name"] == "Updated Name"
    assert asset["type"] == "Entity"
    assert asset["description"] == "Original desc"  # unchanged


@pytest.mark.asyncio
async def test_update_asset_no_fields_is_noop(test_db) -> None:
    """update_asset with no fields logs a warning and leaves record unchanged."""
    model_id = await _make_model()
    asset_id = await crud.create_asset(model_id, "Asset", "Stable", "desc")

    await crud.update_asset(asset_id)  # no fields — should not raise

    asset = await crud.get_asset(asset_id)
    assert asset["name"] == "Stable"


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_flow_returns_correct_record(test_db) -> None:
    """get_flow retrieves the flow by ID."""
    model_id = await _make_model()
    flow_id = await crud.create_flow(
        model_id=model_id,
        flow_type="DataFlow",
        flow_description="User sends credentials to API",
        source_entity="User",
        target_entity="API Gateway",
    )

    flow = await crud.get_flow(flow_id)

    assert flow is not None
    assert flow["id"] == flow_id
    assert flow["flow_type"] == "DataFlow"
    assert flow["source_entity"] == "User"


@pytest.mark.asyncio
async def test_get_flow_returns_none_for_missing(test_db) -> None:
    result = await crud.get_flow("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_update_flow_changes_fields(test_db) -> None:
    """update_flow updates provided fields and leaves others unchanged."""
    model_id = await _make_model()
    flow_id = await crud.create_flow(
        model_id=model_id,
        flow_type="DataFlow",
        flow_description="Original description",
        source_entity="User",
        target_entity="DB",
    )

    await crud.update_flow(
        flow_id=flow_id,
        flow_description="Updated description",
        target_entity="Cache",
    )

    flow = await crud.get_flow(flow_id)
    assert flow["flow_description"] == "Updated description"
    assert flow["target_entity"] == "Cache"
    assert flow["source_entity"] == "User"  # unchanged


@pytest.mark.asyncio
async def test_update_flow_no_fields_is_noop(test_db) -> None:
    """update_flow with no fields logs a warning and leaves record unchanged."""
    model_id = await _make_model()
    flow_id = await crud.create_flow(
        model_id=model_id,
        flow_type="DataFlow",
        flow_description="Stable description",
        source_entity="User",
        target_entity="DB",
    )

    await crud.update_flow(flow_id)  # no fields — should not raise

    flow = await crud.get_flow(flow_id)
    assert flow["flow_description"] == "Stable description"


@pytest.mark.asyncio
async def test_delete_flow_removes_record(test_db) -> None:
    model_id = await _make_model()
    flow_id = await crud.create_flow(
        model_id=model_id,
        flow_type="DataFlow",
        flow_description="desc",
        source_entity="A",
        target_entity="B",
    )

    await crud.delete_flow(flow_id)

    assert await crud.get_flow(flow_id) is None


# ---------------------------------------------------------------------------
# Trust Boundaries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_trust_boundary(test_db) -> None:
    """Full create → get cycle for trust boundaries."""
    model_id = await _make_model()
    boundary_id = await crud.create_trust_boundary(
        model_id=model_id,
        purpose="Separates internet from internal network",
        source_entity="Internet",
        target_entity="DMZ",
    )

    boundary = await crud.get_trust_boundary(boundary_id)

    assert boundary is not None
    assert boundary["id"] == boundary_id
    assert boundary["purpose"] == "Separates internet from internal network"
    assert boundary["source_entity"] == "Internet"


@pytest.mark.asyncio
async def test_list_trust_boundaries_returns_all(test_db) -> None:
    model_id = await _make_model()
    await crud.create_trust_boundary(model_id, "Boundary A", "X", "Y")
    await crud.create_trust_boundary(model_id, "Boundary B", "Y", "Z")

    results = await crud.list_trust_boundaries(model_id)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_delete_trust_boundary_removes_record(test_db) -> None:
    model_id = await _make_model()
    boundary_id = await crud.create_trust_boundary(model_id, "To delete", "A", "B")

    await crud.delete_trust_boundary(boundary_id)

    assert await crud.get_trust_boundary(boundary_id) is None


@pytest.mark.asyncio
async def test_update_trust_boundary_changes_fields(test_db) -> None:
    """update_trust_boundary updates only the provided fields."""
    model_id = await _make_model()
    boundary_id = await crud.create_trust_boundary(model_id, "Old purpose", "Internet", "DMZ")

    await crud.update_trust_boundary(boundary_id, purpose="New purpose", target_entity="LAN")

    boundary = await crud.get_trust_boundary(boundary_id)
    assert boundary["purpose"] == "New purpose"
    assert boundary["target_entity"] == "LAN"
    assert boundary["source_entity"] == "Internet"  # unchanged


@pytest.mark.asyncio
async def test_update_trust_boundary_no_fields_is_noop(test_db) -> None:
    """update_trust_boundary with no fields leaves record unchanged."""
    model_id = await _make_model()
    boundary_id = await crud.create_trust_boundary(model_id, "Stable", "A", "B")

    await crud.update_trust_boundary(boundary_id)  # no fields — should not raise

    boundary = await crud.get_trust_boundary(boundary_id)
    assert boundary["purpose"] == "Stable"


# ---------------------------------------------------------------------------
# clear_model_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_model_data_removes_all_components(test_db) -> None:
    """clear_model_data deletes assets, flows, trust_boundaries, and threats for a model."""
    model_id = await _make_model()

    await crud.create_asset(model_id, "Asset", "DB", "")
    await crud.create_flow(model_id, "data", "A→B", "A", "B")
    await crud.create_trust_boundary(model_id, "Perimeter", "Internet", "DMZ")
    await _make_threat(model_id)

    await crud.clear_model_data(model_id)

    assert await crud.list_assets(model_id) == []
    assert await crud.list_flows(model_id) == []
    assert await crud.list_trust_boundaries(model_id) == []
    threats = await crud.list_threats(model_id)
    assert threats == []


@pytest.mark.asyncio
async def test_clear_model_data_does_not_affect_other_models(test_db) -> None:
    """clear_model_data only removes data for the specified model."""
    model_a = await _make_model()
    model_b = await _make_model()

    await crud.create_asset(model_a, "Asset", "A-DB", "")
    await crud.create_asset(model_b, "Asset", "B-DB", "")

    await crud.clear_model_data(model_a)

    assert await crud.list_assets(model_a) == []
    remaining = await crud.list_assets(model_b)
    assert len(remaining) == 1
    assert remaining[0]["name"] == "B-DB"


# ---------------------------------------------------------------------------
# Threat Sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_threat_source_returns_correct_record(test_db) -> None:
    model_id = await _make_model()
    source_id = await crud.create_threat_source(
        model_id=model_id,
        category="External Attacker",
        description="Motivated adversary with internet access",
        example="Script kiddie attempting SQLi",
    )

    source = await crud.get_threat_source(source_id)

    assert source is not None
    assert source["id"] == source_id
    assert source["category"] == "External Attacker"


@pytest.mark.asyncio
async def test_get_threat_source_returns_none_for_missing(test_db) -> None:
    result = await crud.get_threat_source("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_delete_threat_source_removes_record(test_db) -> None:
    model_id = await _make_model()
    source_id = await crud.create_threat_source(model_id, "Insider", "desc", "example")

    await crud.delete_threat_source(source_id)

    assert await crud.get_threat_source(source_id) is None


# ---------------------------------------------------------------------------
# Attack Trees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_attack_tree(test_db) -> None:
    """Full create → get cycle for attack trees."""
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    mermaid = "graph TD\n  A[Attacker] --> B[SQLi]\n  B --> C[Data Exfil]"

    tree_id = await crud.create_attack_tree(threat_id=threat_id, mermaid_source=mermaid)
    tree = await crud.get_attack_tree(tree_id)

    assert tree is not None
    assert tree["id"] == tree_id
    assert tree["threat_id"] == threat_id
    assert "graph TD" in tree["mermaid_source"]


@pytest.mark.asyncio
async def test_list_attack_trees_for_threat(test_db) -> None:
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)

    await crud.create_attack_tree(threat_id, "graph TD\n  A --> B")
    await crud.create_attack_tree(threat_id, "graph TD\n  C --> D")

    trees = await crud.list_attack_trees(threat_id)
    assert len(trees) == 2


@pytest.mark.asyncio
async def test_delete_attack_tree_removes_record(test_db) -> None:
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    tree_id = await crud.create_attack_tree(threat_id, "graph TD\n  A --> B")

    await crud.delete_attack_tree(tree_id)

    assert await crud.get_attack_tree(tree_id) is None


@pytest.mark.asyncio
async def test_get_attack_tree_returns_none_for_missing(test_db) -> None:
    result = await crud.get_attack_tree("00000000-0000-0000-0000-000000000000")
    assert result is None


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get_test_case(test_db) -> None:
    """Full create → get cycle for test cases."""
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    gherkin = (
        "Given the API accepts user input\n"
        "When an attacker submits ' OR 1=1--\n"
        "Then the database query should be rejected"
    )

    case_id = await crud.create_test_case(threat_id=threat_id, gherkin_source=gherkin)
    case = await crud.get_test_case(case_id)

    assert case is not None
    assert case["id"] == case_id
    assert case["threat_id"] == threat_id
    assert "OR 1=1" in case["gherkin_source"]


@pytest.mark.asyncio
async def test_list_test_cases_for_threat(test_db) -> None:
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)

    await crud.create_test_case(threat_id, "Given A\nWhen B\nThen C")
    await crud.create_test_case(threat_id, "Given D\nWhen E\nThen F")

    cases = await crud.list_test_cases(threat_id)
    assert len(cases) == 2


@pytest.mark.asyncio
async def test_delete_test_case_removes_record(test_db) -> None:
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    case_id = await crud.create_test_case(threat_id, "Given A\nWhen B\nThen C")

    await crud.delete_test_case(case_id)

    assert await crud.get_test_case(case_id) is None


@pytest.mark.asyncio
async def test_get_test_case_returns_none_for_missing(test_db) -> None:
    result = await crud.get_test_case("00000000-0000-0000-0000-000000000000")
    assert result is None


@pytest.mark.asyncio
async def test_attack_tree_cascade_deleted_with_threat(test_db) -> None:
    """Deleting a threat removes its attack trees via CASCADE."""
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    tree_id = await crud.create_attack_tree(threat_id, "graph TD\n  A --> B")

    await crud.delete_threat(threat_id)

    assert await crud.get_attack_tree(tree_id) is None


@pytest.mark.asyncio
async def test_test_case_cascade_deleted_with_threat(test_db) -> None:
    """Deleting a threat removes its test cases via CASCADE."""
    model_id = await _make_model()
    threat_id = await _make_threat(model_id)
    case_id = await crud.create_test_case(threat_id, "Given A\nWhen B\nThen C")

    await crud.delete_threat(threat_id)

    assert await crud.get_test_case(case_id) is None
