"""Tests for the AWS Bedrock provider (backend/providers/bedrock.py).

All tests mock boto3 — no AWS credentials or network access required.
"""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import botocore.exceptions as _bce
import pytest
from pydantic import BaseModel

from backend.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    create_provider,
)
from backend.providers.bedrock import BedrockProvider


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _SimpleModel(BaseModel):
    value: str
    count: int


def _make_tool_response(data: dict, stop_reason: str = "tool_use") -> dict:
    """Build a minimal Converse API response that contains a toolUse block."""
    return {
        "stopReason": stop_reason,
        "output": {"message": {"content": [{"toolUse": {"name": "respond", "input": data}}]}},
    }


def _make_text_response(text: str) -> dict:
    """Build a minimal Converse API response that contains a text block."""
    return {
        "stopReason": "end_turn",
        "output": {"message": {"content": [{"text": text}]}},
    }


def _make_client_error(code: str, message: str = "test error") -> Any:
    """Create a botocore ClientError with the given error code."""
    import botocore.exceptions

    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": message}},
        "Converse",
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_bedrock_rejects_plain_api_model_id():
    """Plain API model IDs (no '.') must be rejected with a clear error."""
    with patch.dict(
        sys.modules, {"boto3": MagicMock(), "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        with pytest.raises(ValueError, match="Bedrock model ID"):
            BedrockProvider(model="claude-sonnet-4-20250514")


def test_bedrock_import_error(monkeypatch):
    """Missing boto3 raises ImportError with pip install hint."""
    monkeypatch.setitem(sys.modules, "boto3", None)
    monkeypatch.setitem(sys.modules, "botocore", None)
    monkeypatch.setitem(sys.modules, "botocore.config", None)

    with pytest.raises(ImportError, match="pip install paranoid-cli\\[bedrock\\]"):
        BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")


# ---------------------------------------------------------------------------
# generate_structured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bedrock_generate_structured():
    """Happy path: mock converse returns a toolUse block, model validates it."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.return_value = _make_tool_response({"value": "hello", "count": 3})

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        result = await provider.generate_structured("test prompt", _SimpleModel)

    assert isinstance(result, _SimpleModel)
    assert result.value == "hello"
    assert result.count == 3


@pytest.mark.asyncio
async def test_bedrock_generate_plain_text():
    """generate() returns the text block content."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.return_value = _make_text_response("hello world")

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="amazon.nova-pro-v1:0")
        result = await provider.generate("test prompt")

    assert result == "hello world"


@pytest.mark.asyncio
async def test_bedrock_auto_bump():
    """max_tokens doubles when stopReason=max_tokens, up to _MAX_AUTO_BUMP."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client

    call_count = 0
    max_tokens_seen: list[int] = []

    def _converse(**kwargs):
        nonlocal call_count
        call_count += 1
        max_tokens_seen.append(kwargs["inferenceConfig"]["maxTokens"])
        if call_count == 1:
            return {"stopReason": "max_tokens", "output": {"message": {"content": []}}}
        return _make_tool_response({"value": "ok", "count": 1})

    mock_client.converse.side_effect = _converse

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        result = await provider.generate_structured("test", _SimpleModel, max_tokens=512)

    assert call_count == 2
    assert max_tokens_seen[1] == 1024  # 512 * 2
    assert result.value == "ok"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bedrock_auth_error_no_credentials():
    """botocore.NoCredentialsError maps to ProviderAuthError."""
    import botocore.exceptions

    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.side_effect = botocore.exceptions.NoCredentialsError()

    with patch.dict(
        sys.modules,
        {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.config": MagicMock(),
            "botocore.exceptions": _bce,
        },
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderAuthError):
            await provider.generate_structured("test", _SimpleModel)


@pytest.mark.asyncio
async def test_bedrock_rate_limit():
    """ThrottlingException ClientError maps to ProviderRateLimitError."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.side_effect = _make_client_error("ThrottlingException")

    with patch.dict(
        sys.modules,
        {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.config": MagicMock(),
            "botocore.exceptions": _bce,
        },
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderRateLimitError):
            await provider.generate_structured("test", _SimpleModel)


@pytest.mark.asyncio
async def test_bedrock_model_timeout():
    """ModelTimeoutException ClientError maps to ProviderTimeoutError."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.side_effect = _make_client_error("ModelTimeoutException")

    with patch.dict(
        sys.modules,
        {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.config": MagicMock(),
            "botocore.exceptions": _bce,
        },
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderTimeoutError):
            await provider.generate_structured("test", _SimpleModel)


@pytest.mark.asyncio
async def test_bedrock_access_denied():
    """AccessDeniedException ClientError maps to ProviderAuthError."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.side_effect = _make_client_error("AccessDeniedException")

    with patch.dict(
        sys.modules,
        {
            "boto3": mock_boto3,
            "botocore": MagicMock(),
            "botocore.config": MagicMock(),
            "botocore.exceptions": _bce,
        },
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderAuthError):
            await provider.generate_structured("test", _SimpleModel)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_create_provider_bedrock():
    """create_provider('bedrock') returns a BedrockProvider instance."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = create_provider(
            provider_type="bedrock",
            model="us.anthropic.claude-sonnet-4-20250514-v1:0",
            region="us-west-2",
        )

    assert isinstance(provider, BedrockProvider)
    assert provider.name == "bedrock"
    assert provider.model == "us.anthropic.claude-sonnet-4-20250514-v1:0"
