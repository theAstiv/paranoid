"""Tests for LLM providers."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import Asset, AssetsList, AssetType
from backend.providers import (
    AnthropicProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    create_provider,
)


# Test fixtures


@pytest.fixture
def sample_asset_list():
    """Sample AssetsList for structured output tests."""
    return AssetsList(
        assets=[
            Asset(type=AssetType.ASSET, name="Database", description="PostgreSQL DB"),
            Asset(type=AssetType.ENTITY, name="User", description="End user"),
        ]
    )


# Anthropic Provider Tests


@pytest.mark.asyncio
async def test_anthropic_generate_structured(sample_asset_list):
    """Test Anthropic structured output generation."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        # Mock response
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "assets": [
                            {
                                "type": "Asset",
                                "name": "Database",
                                "description": "PostgreSQL DB",
                            },
                            {
                                "type": "Entity",
                                "name": "User",
                                "description": "End user",
                            },
                        ]
                    }
                )
            )
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")
        result = await provider.generate_structured(
            prompt="List the assets",
            response_model=AssetsList,
        )

        assert isinstance(result, AssetsList)
        assert len(result.assets) == 2
        assert result.assets[0].name == "Database"


@pytest.mark.asyncio
async def test_anthropic_generate_plain_text():
    """Test Anthropic plain text generation."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        # Mock response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="This is a test response")]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")
        result = await provider.generate(prompt="Hello")

        assert result == "This is a test response"


@pytest.mark.asyncio
async def test_anthropic_auth_error():
    """Test Anthropic authentication error handling."""
    from anthropic import AuthenticationError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        # Create a mock error with required parameters
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = AuthenticationError(
            message="Invalid API key", response=mock_response, body={"error": "Unauthorized"}
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = mock_error
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-4", api_key="bad-key")

        with pytest.raises(ProviderAuthError):
            await provider.generate(prompt="Hello")


@pytest.mark.asyncio
async def test_anthropic_rate_limit_error():
    """Test Anthropic rate limit error handling."""
    from anthropic import RateLimitError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        # Create a mock error with required parameters
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_error = RateLimitError(
            message="Rate limit exceeded",
            response=mock_response,
            body={"error": "Rate limit exceeded"},
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = mock_error
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

        with pytest.raises(ProviderRateLimitError):
            await provider.generate(prompt="Hello")


# OpenAI Provider Tests


@pytest.mark.asyncio
async def test_openai_generate_structured(sample_asset_list):
    """Test OpenAI structured output generation."""
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        # Mock response
        mock_message = MagicMock()
        mock_message.content = json.dumps(
            {
                "assets": [
                    {
                        "type": "Asset",
                        "name": "Database",
                        "description": "PostgreSQL DB",
                    },
                    {"type": "Entity", "name": "User", "description": "End user"},
                ]
            }
        )

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        result = await provider.generate_structured(
            prompt="List the assets",
            response_model=AssetsList,
        )

        assert isinstance(result, AssetsList)
        assert len(result.assets) == 2


@pytest.mark.asyncio
async def test_openai_generate_plain_text():
    """Test OpenAI plain text generation."""
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        mock_message = MagicMock()
        mock_message.content = "This is a test response"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4", api_key="test-key")
        result = await provider.generate(prompt="Hello")

        assert result == "This is a test response"


@pytest.mark.asyncio
async def test_openai_auth_error():
    """Test OpenAI authentication error handling."""
    from openai import AuthenticationError

    with patch("backend.providers.openai.OpenAI") as mock_openai:
        # Create a mock error with required parameters
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_error = AuthenticationError(
            message="Invalid API key", response=mock_response, body={"error": "Unauthorized"}
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = mock_error
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4", api_key="bad-key")

        with pytest.raises(ProviderAuthError):
            await provider.generate(prompt="Hello")


# Ollama Provider Tests


@pytest.mark.asyncio
async def test_ollama_generate_structured(sample_asset_list):
    """Test Ollama structured output generation."""
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        # Mock HTTP response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps(
                {
                    "assets": [
                        {
                            "type": "Asset",
                            "name": "Database",
                            "description": "PostgreSQL DB",
                        },
                        {
                            "type": "Entity",
                            "name": "User",
                            "description": "End user",
                        },
                    ]
                }
            )
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_structured(
            prompt="List the assets",
            response_model=AssetsList,
        )

        assert isinstance(result, AssetsList)
        assert len(result.assets) == 2


@pytest.mark.asyncio
async def test_ollama_generate_plain_text():
    """Test Ollama plain text generation."""
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "This is a test response"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate(prompt="Hello")

        assert result == "This is a test response"


@pytest.mark.asyncio
async def test_ollama_connection_error():
    """Test Ollama connection error handling."""
    import httpx

    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.RequestError("Connection refused")
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")

        with pytest.raises(ProviderError) as exc_info:
            await provider.generate(prompt="Hello")

        assert "is Ollama running" in str(exc_info.value)


# Factory Tests


def test_create_provider_anthropic():
    """Test provider factory for Anthropic."""
    provider = create_provider("anthropic", model="claude-sonnet-4", api_key="test-key")
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"
    assert provider.model == "claude-sonnet-4"


def test_create_provider_openai():
    """Test provider factory for OpenAI."""
    provider = create_provider("openai", model="gpt-4", api_key="test-key")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"
    assert provider.model == "gpt-4"


def test_create_provider_ollama():
    """Test provider factory for Ollama."""
    provider = create_provider("ollama", model="llama3")
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"
    assert provider.model == "llama3"


def test_create_provider_invalid():
    """Test provider factory with invalid provider type."""
    with pytest.raises(ValueError, match="Unsupported provider"):
        create_provider("invalid", model="test", api_key="test-key")


def test_create_provider_missing_api_key():
    """Test provider factory with missing API key."""
    with pytest.raises(ValueError, match="api_key required"):
        create_provider("anthropic", model="claude-sonnet-4")

    with pytest.raises(ValueError, match="api_key required"):
        create_provider("openai", model="gpt-4")


# Property Tests


def test_provider_properties():
    """Test provider name and model properties."""
    with patch("backend.providers.anthropic.Anthropic"):
        anthropic = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")
        assert anthropic.name == "anthropic"
        assert anthropic.model == "claude-sonnet-4"

    with patch("backend.providers.openai.OpenAI"):
        openai = OpenAIProvider(model="gpt-4", api_key="test-key")
        assert openai.name == "openai"
        assert openai.model == "gpt-4"

    ollama = OllamaProvider(model="llama3")
    assert ollama.name == "ollama"
    assert ollama.model == "llama3"
