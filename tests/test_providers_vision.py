"""Tests for provider vision API integration (backend/providers/).

Tests vision message construction for Anthropic, OpenAI, and Ollama providers.
Uses mocks to verify content blocks are constructed correctly without calling APIs.
"""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from backend.models.extended import ImageContent
from backend.providers.anthropic import AnthropicProvider
from backend.providers.ollama import OllamaProvider
from backend.providers.openai import OpenAIProvider


class TestResponse(BaseModel):
    """Test response model for structured output."""

    message: str


# ---------------------------------------------------------------------------
# Anthropic vision tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_vision_with_image():
    """Test Anthropic provider constructs vision content blocks correctly."""
    provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

    # Mock the Anthropic client
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"message": "Architecture analyzed"}')]

    # Create a mock that captures arguments but returns mock_response
    async def mock_executor(func, *args, **kwargs):
        """Mock run_sync_in_executor that calls the function to capture args."""
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = MagicMock(return_value=mock_response)

        # Create test image
        image = ImageContent(
            data="iVBORw0KGgo...",  # Minimal base64
            media_type="image/png",
            source="test.png",
        )

        # Call with vision
        with patch("backend.providers.anthropic.run_sync_in_executor", new=mock_executor):
            result = await provider.generate_structured(
                prompt="Analyze this architecture diagram",
                response_model=TestResponse,
                images=[image],
            )

        # Verify content blocks were constructed correctly
        call_kwargs = mock_client.messages.create.call_args[1]
        message_content = call_kwargs["messages"][0]["content"]

        # Should have 2 content blocks: image + text
        assert len(message_content) == 2

        # First block should be image
        assert message_content[0]["type"] == "image"
        assert message_content[0]["source"]["type"] == "base64"
        assert message_content[0]["source"]["media_type"] == "image/png"
        assert message_content[0]["source"]["data"] == "iVBORw0KGgo..."

        # Second block should be text
        assert message_content[1]["type"] == "text"
        assert message_content[1]["text"] == "Analyze this architecture diagram"

        assert result.message == "Architecture analyzed"


@pytest.mark.asyncio
async def test_anthropic_vision_with_multiple_images():
    """Test Anthropic provider handles multiple images."""
    provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"message": "Done"}')]

    async def mock_executor(func, *args, **kwargs):
        """Mock run_sync_in_executor that calls the function to capture args."""
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = MagicMock(return_value=mock_response)

        images = [
            ImageContent(data="image1", media_type="image/png", source="1.png"),
            ImageContent(data="image2", media_type="image/jpeg", source="2.jpg"),
        ]

        with patch("backend.providers.anthropic.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="Compare diagrams",
                response_model=TestResponse,
                images=images,
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        message_content = call_kwargs["messages"][0]["content"]

        # Should have 3 blocks: image1 + image2 + text
        assert len(message_content) == 3
        assert message_content[0]["type"] == "image"
        assert message_content[1]["type"] == "image"
        assert message_content[2]["type"] == "text"


@pytest.mark.asyncio
async def test_anthropic_vision_without_images():
    """Test Anthropic provider works without images (backward compat)."""
    provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"message": "Text only"}')]

    async def mock_executor(func, *args, **kwargs):
        """Mock run_sync_in_executor that calls the function to capture args."""
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = MagicMock(return_value=mock_response)

        with patch("backend.providers.anthropic.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="No images",
                response_model=TestResponse,
                images=None,
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        message_content = call_kwargs["messages"][0]["content"]

        # Should have only 1 block: text
        assert len(message_content) == 1
        assert message_content[0]["type"] == "text"


# ---------------------------------------------------------------------------
# OpenAI vision tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_vision_with_image():
    """Test OpenAI provider constructs image_url content blocks correctly."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    # Mock the OpenAI client
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"message": "Diagram analyzed"}'))]

    async def mock_executor(func, *args, **kwargs):
        """Mock run_sync_in_executor that calls the function to capture args."""
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.create = MagicMock(return_value=mock_response)

        image = ImageContent(
            data="base64data",
            media_type="image/jpeg",
            source="arch.jpg",
        )

        with patch("backend.providers.openai.run_sync_in_executor", new=mock_executor):
            result = await provider.generate_structured(
                prompt="Describe the architecture",
                response_model=TestResponse,
                images=[image],
            )

        # Verify content blocks
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        user_message = call_kwargs["messages"][1]  # Second message (after system)
        user_content = user_message["content"]

        # Should have 2 blocks: image_url + text
        assert len(user_content) == 2

        # First block should be image_url with data URI
        assert user_content[0]["type"] == "image_url"
        assert user_content[0]["image_url"]["url"] == "data:image/jpeg;base64,base64data"

        # Second block should be text
        assert user_content[1]["type"] == "text"
        assert user_content[1]["text"] == "Describe the architecture"

        assert result.message == "Diagram analyzed"


@pytest.mark.asyncio
async def test_openai_vision_without_images():
    """Test OpenAI provider works without images (backward compat)."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"message": "Text only"}'))]

    async def mock_executor(func, *args, **kwargs):
        """Mock run_sync_in_executor that calls the function to capture args."""
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.create = MagicMock(return_value=mock_response)

        with patch("backend.providers.openai.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="No images",
                response_model=TestResponse,
                images=None,
            )

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        user_message = call_kwargs["messages"][1]
        user_content = user_message["content"]

        # Should have only 1 block: text
        assert len(user_content) == 1
        assert user_content[0]["type"] == "text"


# ---------------------------------------------------------------------------
# Ollama graceful degradation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_vision_logs_warning_and_continues():
    """Test Ollama provider logs warning when images provided but continues without them."""
    provider = OllamaProvider(model="llama3")

    mock_response = MagicMock()
    mock_response.json.return_value = {"response": '{"message": "Text processed"}'}
    mock_response.raise_for_status = MagicMock()

    with patch.object(provider, "_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)

        image = ImageContent(
            data="base64data",
            media_type="image/png",
            source="test.png",
        )

        # Should log warning but not raise
        with patch("backend.providers.ollama.logger") as mock_logger:
            result = await provider.generate_structured(
                prompt="Analyze diagram",
                response_model=TestResponse,
                images=[image],
            )

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            warning_message = mock_logger.warning.call_args[0][0]
            assert "does not support vision" in warning_message
            assert "Anthropic or OpenAI" in warning_message

        # Verify API call was made without images
        call_kwargs = mock_client.post.call_args[1]
        # Ollama doesn't have an images parameter in the request
        assert "images" not in call_kwargs["json"]

        assert result.message == "Text processed"


@pytest.mark.asyncio
async def test_ollama_vision_without_images_no_warning():
    """Test Ollama provider doesn't log warning when no images provided."""
    provider = OllamaProvider(model="llama3")

    mock_response = MagicMock()
    mock_response.json.return_value = {"response": '{"message": "Done"}'}
    mock_response.raise_for_status = MagicMock()

    with patch.object(provider, "_client") as mock_client:
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("backend.providers.ollama.logger") as mock_logger:
            await provider.generate_structured(
                prompt="No images",
                response_model=TestResponse,
                images=None,
            )

            # Should NOT log warning
            mock_logger.warning.assert_not_called()
