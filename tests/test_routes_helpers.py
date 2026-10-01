"""Tests for shared route helper utilities (backend/routes/_helpers.py)."""

import sys
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.config import settings
from backend.routes._helpers import (
    anthropic_kwargs,
    bedrock_kwargs,
    build_fast_provider,
    build_provider_from_record,
)


def test_anthropic_kwargs_passes_effort_only_for_anthropic_when_set(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_effort", "medium")
    assert anthropic_kwargs("anthropic") == {"effort": "medium"}
    assert anthropic_kwargs("openai") == {}
    assert anthropic_kwargs("bedrock") == {}


def test_anthropic_kwargs_unset_effort_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_effort", None)
    assert anthropic_kwargs("anthropic") == {}


def test_effort_reaches_main_provider_but_not_fast_provider(monkeypatch):
    """Haiku (the fast model) rejects `effort`, so only the main model gets it."""
    monkeypatch.setattr(settings, "anthropic_effort", "medium")
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    monkeypatch.setattr(settings, "fast_model", "claude-haiku-4-5-20251001")
    record = {"provider": "anthropic", "model": "claude-sonnet-5"}

    assert build_provider_from_record(record)._effort == "medium"
    assert build_fast_provider(record)._effort is None


def test_anthropic_effort_setting_validates_and_treats_blank_as_unset(monkeypatch):
    from pydantic import ValidationError

    from backend.config import Settings

    monkeypatch.setenv("ANTHROPIC_EFFORT", "")
    assert Settings().anthropic_effort is None
    monkeypatch.setenv("ANTHROPIC_EFFORT", "medium")
    assert Settings().anthropic_effort == "medium"
    monkeypatch.setenv("ANTHROPIC_EFFORT", "bogus")
    with pytest.raises(ValidationError):
        Settings()


def test_bedrock_kwargs_non_bedrock_returns_empty():
    assert bedrock_kwargs("anthropic") == {}
    assert bedrock_kwargs("openai") == {}
    assert bedrock_kwargs("ollama") == {}


def test_bedrock_kwargs_bedrock_returns_region_profile(monkeypatch):
    monkeypatch.setattr(settings, "aws_region", "eu-west-1")
    monkeypatch.setattr(settings, "aws_profile", "staging")
    result = bedrock_kwargs("bedrock")
    assert result == {"region": "eu-west-1", "profile": "staging"}


def test_bedrock_kwargs_bedrock_empty_region_profile(monkeypatch):
    monkeypatch.setattr(settings, "aws_region", "")
    monkeypatch.setattr(settings, "aws_profile", "")
    result = bedrock_kwargs("bedrock")
    assert result == {"region": "", "profile": ""}


def test_build_provider_from_record_passes_bedrock_kwargs(monkeypatch):
    """build_provider_from_record forwards region/profile to create_provider for bedrock."""
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    monkeypatch.setattr(settings, "aws_profile", "test-profile")
    monkeypatch.setattr(settings, "default_provider", "bedrock")
    monkeypatch.setattr(settings, "default_model", "us.anthropic.claude-sonnet-4-20250514-v1:0")

    captured: dict = {}
    fake_provider = MagicMock()

    def _fake_create(provider_type, model, **kwargs):
        captured.update(kwargs)
        return fake_provider

    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)

    from backend.routes._helpers import build_provider_from_record

    result = build_provider_from_record(
        {"provider": "bedrock", "model": "us.anthropic.claude-sonnet-4-20250514-v1:0"}
    )

    assert result is fake_provider
    assert captured.get("region") == "us-west-2"
    assert captured.get("profile") == "test-profile"


def test_build_provider_missing_boto3_returns_422(monkeypatch):
    """When boto3 is absent, bedrock provider raises HTTPException(422) with pip hint."""
    monkeypatch.setattr(settings, "default_provider", "bedrock")
    monkeypatch.setattr(settings, "default_model", "us.anthropic.claude-sonnet-4-20250514-v1:0")
    monkeypatch.setattr(settings, "aws_region", "")
    monkeypatch.setattr(settings, "aws_profile", "")

    # Force boto3 import to fail inside BedrockProvider.__init__
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setitem(sys.modules, "botocore", None)
    monkeypatch.setitem(sys.modules, "botocore.config", None)

    # Ensure bedrock.py is not cached with a working import
    sys.modules.pop("backend.providers.bedrock", None)

    from backend.routes._helpers import build_provider_from_record

    with pytest.raises(HTTPException) as exc_info:
        build_provider_from_record(
            {"provider": "bedrock", "model": "us.anthropic.claude-sonnet-4-20250514-v1:0"}
        )

    assert exc_info.value.status_code == 422
    assert "pip install paranoid-cli[bedrock]" in exc_info.value.detail
