"""Tests for database CRUD operations.

Uses shared test_db fixture from conftest.py (function scope, fresh DB per test).
"""

import pytest

from backend.db import crud


@pytest.mark.asyncio
async def test_create_and_get_threat_model(test_db):
    """Test creating and retrieving a threat model."""
    model_id = await crud.create_threat_model(
        db_path=test_db,
        title="Test Model",
        description="Test description",
        provider="anthropic",
        model="claude-sonnet-4",
        framework="STRIDE",
        iteration_count=3,
    )

    assert model_id is not None
    assert len(model_id) > 0

    # Retrieve the model
    model = await crud.get_threat_model(test_db, model_id)
    assert model is not None
    assert model["title"] == "Test Model"
    assert model["description"] == "Test description"
    assert model["provider"] == "anthropic"
    assert model["framework"] == "STRIDE"
    assert model["iteration_count"] == 3
    assert model["status"] == "pending"


@pytest.mark.asyncio
async def test_update_threat_model(test_db):
    """Test updating threat model fields."""
    model_id = await crud.create_threat_model(
        db_path=test_db,
        title="Original Title",
        description="Original description",
        provider="anthropic",
        model="claude-sonnet-4",
    )

    # Update the model
    await crud.update_threat_model(
        db_path=test_db,
        model_id=model_id,
        title="Updated Title",
        description="Updated description",
        status="in_progress",
    )

    # Verify updates
    model = await crud.get_threat_model(test_db, model_id)
    assert model["title"] == "Updated Title"
    assert model["description"] == "Updated description"
    assert model["status"] == "in_progress"


@pytest.mark.asyncio
async def test_list_threat_models(test_db):
    """Test listing threat models."""
    # Create multiple models
    await crud.create_threat_model(test_db, "Model 1", "Desc 1", "anthropic", "claude-sonnet-4")
    await crud.create_threat_model(test_db, "Model 2", "Desc 2", "openai", "gpt-4")
    await crud.create_threat_model(test_db, "Model 3", "Desc 3", "ollama", "llama3")

    # List models
    models = await crud.list_threat_models(test_db)
    assert len(models) == 3
    assert models[0]["title"] == "Model 3"  # Most recent first


@pytest.mark.asyncio
async def test_create_and_get_threat(test_db):
    """Test creating and retrieving a threat."""
    # Create a model first
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create a threat
    threat_id = await crud.create_threat(
        db_path=test_db,
        model_id=model_id,
        name="SQL Injection",
        description="SQL injection vulnerability in login form",
        target="Database",
        impact="High",
        likelihood="Medium",
        mitigations=["Use parameterized queries", "Input validation"],
        stride_category="Tampering",
        dread_score=7.5,
        iteration_number=1,
    )

    assert threat_id is not None

    # Retrieve the threat
    threat = await crud.get_threat(test_db, threat_id)
    assert threat is not None
    assert threat["name"] == "SQL Injection"
    assert threat["stride_category"] == "Tampering"
    assert threat["dread_score"] == 7.5
    assert len(threat["mitigations"]) == 2
    assert threat["status"] == "pending"


@pytest.mark.asyncio
async def test_update_threat(test_db):
    """Test updating threat details."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    threat_id = await crud.create_threat(
        db_path=test_db,
        model_id=model_id,
        name="Original Threat",
        description="Original description",
        target="API",
        impact="Medium",
        likelihood="Low",
        mitigations=["Mitigation 1"],
    )

    # Update the threat
    await crud.update_threat(
        db_path=test_db,
        threat_id=threat_id,
        name="Updated Threat",
        impact="High",
        dread_damage=8,
        dread_reproducibility=7,
        dread_exploitability=6,
        dread_affected_users=9,
        dread_discoverability=5,
        dread_score=7.0,
        mitigations=["Mitigation 1", "Mitigation 2", "Mitigation 3"],
    )

    # Verify updates
    threat = await crud.get_threat(test_db, threat_id)
    assert threat["name"] == "Updated Threat"
    assert threat["impact"] == "High"
    assert threat["dread_damage"] == 8
    assert threat["dread_score"] == 7.0
    assert len(threat["mitigations"]) == 3


@pytest.mark.asyncio
async def test_list_threats_with_filter(test_db):
    """Test listing threats with status filter."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create threats with different statuses
    threat1_id = await crud.create_threat(
        test_db, model_id, "Threat 1", "Desc 1", "Target", "High", "Low", ["Mit"]
    )
    threat2_id = await crud.create_threat(
        test_db, model_id, "Threat 2", "Desc 2", "Target", "High", "Low", ["Mit"]
    )
    threat3_id = await crud.create_threat(
        test_db, model_id, "Threat 3", "Desc 3", "Target", "High", "Low", ["Mit"]
    )

    # Update statuses
    await crud.update_threat_status(test_db, threat1_id, "approved")
    await crud.update_threat_status(test_db, threat3_id, "approved")

    # List all threats
    all_threats = await crud.list_threats(test_db, model_id)
    assert len(all_threats) == 3

    # List only approved threats
    approved_threats = await crud.list_threats(test_db, model_id, status="approved")
    assert len(approved_threats) == 2

    # List only pending threats
    pending_threats = await crud.list_threats(test_db, model_id, status="pending")
    assert len(pending_threats) == 1


@pytest.mark.asyncio
async def test_delete_threat(test_db):
    """Test deleting a threat."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    threat_id = await crud.create_threat(
        test_db, model_id, "Threat", "Desc", "Target", "High", "Low", ["Mit"]
    )

    # Delete the threat
    await crud.delete_threat(test_db, threat_id)

    # Verify deletion
    threat = await crud.get_threat(test_db, threat_id)
    assert threat is None


@pytest.mark.asyncio
async def test_create_and_list_assets(test_db):
    """Test creating and listing assets."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create assets
    await crud.create_asset(test_db, model_id, "Asset", "Database", "PostgreSQL database")
    await crud.create_asset(test_db, model_id, "Entity", "User", "End user")

    # List assets
    assets = await crud.list_assets(test_db, model_id)
    assert len(assets) == 2
    assert assets[0]["name"] == "Database"
    assert assets[1]["name"] == "User"


@pytest.mark.asyncio
async def test_update_asset(test_db):
    """Test updating asset details."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    asset_id = await crud.create_asset(test_db, model_id, "Asset", "API", "REST API")

    # Update asset
    await crud.update_asset(
        test_db,
        asset_id,
        name="GraphQL API",
        description="GraphQL API endpoint",
    )

    # Verify update
    assets = await crud.list_assets(test_db, model_id)
    assert len(assets) == 1
    assert assets[0]["name"] == "GraphQL API"
    assert assets[0]["description"] == "GraphQL API endpoint"


@pytest.mark.asyncio
async def test_create_and_list_flows(test_db):
    """Test creating and listing data flows."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create flows
    await crud.create_flow(
        test_db,
        model_id,
        "data_flow",
        "User authentication",
        "Client",
        "API Gateway",
    )
    await crud.create_flow(test_db, model_id, "data_flow", "Database query", "API", "Database")

    # List flows
    flows = await crud.list_flows(test_db, model_id)
    assert len(flows) == 2
    assert flows[0]["source_entity"] == "Client"
    assert flows[1]["target_entity"] == "Database"


@pytest.mark.asyncio
async def test_pipeline_run_tracking(test_db):
    """Test pipeline run audit logging."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create pipeline runs
    await crud.create_pipeline_run(
        db_path=test_db,
        model_id=model_id,
        iteration=1,
        step="summarize",
        input_hash="abc123",
        output_hash="def456",
        provider="anthropic",
        duration_ms=1500,
        tokens_used=250,
    )

    await crud.create_pipeline_run(
        db_path=test_db,
        model_id=model_id,
        iteration=1,
        step="extract_assets",
        input_hash="def456",
        output_hash="ghi789",
        provider="anthropic",
        duration_ms=2000,
        tokens_used=300,
    )

    # Get statistics
    stats = await crud.get_pipeline_stats(test_db, model_id)
    assert stats["total_steps"] == 2
    assert stats["total_duration_ms"] == 3500
    assert stats["total_tokens"] == 550


@pytest.mark.asyncio
async def test_cascade_delete_threat_model(test_db):
    """Test that deleting a model cascades to threats, assets, and flows."""
    model_id = await crud.create_threat_model(
        test_db, "Test Model", "Desc", "anthropic", "claude-sonnet-4"
    )

    # Create related records
    threat_id = await crud.create_threat(
        test_db, model_id, "Threat", "Desc", "Target", "High", "Low", ["Mit"]
    )
    await crud.create_asset(test_db, model_id, "Asset", "Database", "DB")
    await crud.create_flow(test_db, model_id, "flow", "Data", "A", "B")

    # Delete the model
    await crud.delete_threat_model(test_db, model_id)

    # Verify all related records are deleted
    model = await crud.get_threat_model(test_db, model_id)
    assert model is None

    threat = await crud.get_threat(test_db, threat_id)
    assert threat is None

    assets = await crud.list_assets(test_db, model_id)
    assert len(assets) == 0

    flows = await crud.list_flows(test_db, model_id)
    assert len(flows) == 0
