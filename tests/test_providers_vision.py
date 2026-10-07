"""Tests for provider vision API integration (backend/providers/).

Tests vision message construction for Anthropic, OpenAI, and Ollama providers.
Uses mocks to verify content blocks are constructed correctly without calling APIs.
"""

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

        # With >1 image, a "Diagram i of n" label precedes each image:
        # label1 + image1 + label2 + image2 + prompt text = 5 blocks.
        assert len(message_content) == 5
        assert message_content[0] == {"type": "text", "text": "Image 1 of 2: 1.png"}
        assert message_content[1]["type"] == "image"
        assert message_content[2] == {"type": "text", "text": "Image 2 of 2: 2.jpg"}
        assert message_content[3]["type"] == "image"
        assert message_content[4]["type"] == "text"
        assert message_content[4]["text"] == "Compare diagrams"


@pytest.mark.asyncio
async def test_anthropic_vision_cache_control_only_on_last_image():
    """5 images + shared_context stays within Anthropic's 4-breakpoint cap.

    Every image used to get its own cache_control block whenever
    shared_context was present; with the system block and the
    shared_context block, 5 images would total 7 breakpoints against
    Anthropic's documented limit of 4. Only the last image may be marked.
    """
    provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"message": "Done"}')]

    async def mock_executor(func, *args, **kwargs):
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.messages.create = MagicMock(return_value=mock_response)

        images = [
            ImageContent(data=f"image{i}", media_type="image/png", source=f"{i}.png")
            for i in range(1, 6)
        ]

        with patch("backend.providers.anthropic.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="Review all diagrams",
                response_model=TestResponse,
                images=images,
                shared_context="stable shared context block",
            )

        call_kwargs = mock_client.messages.create.call_args[1]
        message_content = call_kwargs["messages"][0]["content"]
        system = call_kwargs["system"]

        breakpoints = sum(1 for block in system if "cache_control" in block)
        breakpoints += sum(1 for block in message_content if "cache_control" in block)
        assert breakpoints <= 4

        image_blocks = [b for b in message_content if b["type"] == "image"]
        assert len(image_blocks) == 5
        assert all("cache_control" not in b for b in image_blocks[:-1])
        assert image_blocks[-1]["cache_control"] == {"type": "ephemeral"}


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
    """Test OpenAI provider constructs image_url content blocks correctly (parse API)."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    # parse() returns the Pydantic model on message.parsed
    parsed_result = TestResponse(message="Diagram analyzed")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(parsed=parsed_result, refusal=None))]

    async def mock_executor(func, *args, **kwargs):
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.parse = MagicMock(return_value=mock_response)

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

        # Verify content blocks passed to parse()
        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        user_message = call_kwargs["messages"][0]  # single user message (no system msg)
        user_content = user_message["content"]

        # Should have 2 blocks: image_url + text
        assert len(user_content) == 2
        assert user_content[0]["type"] == "image_url"
        assert user_content[0]["image_url"]["url"] == "data:image/jpeg;base64,base64data"
        assert user_content[1]["type"] == "text"
        assert user_content[1]["text"] == "Describe the architecture"

        assert result.message == "Diagram analyzed"


@pytest.mark.asyncio
async def test_openai_vision_with_multiple_images():
    """With >1 image, a 'Image i of n' label precedes each image_url block."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    parsed_result = TestResponse(message="Done")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(parsed=parsed_result, refusal=None))]

    async def mock_executor(func, *args, **kwargs):
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.parse = MagicMock(return_value=mock_response)

        images = [
            ImageContent(data="image1", media_type="image/png", source="1.png"),
            ImageContent(data="image2", media_type="image/jpeg", source="2.jpg"),
        ]

        with patch("backend.providers.openai.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="Compare diagrams",
                response_model=TestResponse,
                images=images,
            )

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        user_content = call_kwargs["messages"][0]["content"]

        # label1 + image1 + label2 + image2 + prompt text = 5 blocks.
        assert len(user_content) == 5
        assert user_content[0] == {"type": "text", "text": "Image 1 of 2: 1.png"}
        assert user_content[1]["type"] == "image_url"
        assert user_content[2] == {"type": "text", "text": "Image 2 of 2: 2.jpg"}
        assert user_content[3]["type"] == "image_url"
        assert user_content[4]["type"] == "text"
        assert user_content[4]["text"] == "Compare diagrams"


@pytest.mark.asyncio
async def test_openai_vision_without_images():
    """Test OpenAI provider works without images (backward compat, parse API)."""
    provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

    parsed_result = TestResponse(message="Text only")
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(parsed=parsed_result, refusal=None))]

    async def mock_executor(func, *args, **kwargs):
        func(*args, **kwargs)
        return mock_response

    with patch.object(provider, "_client") as mock_client:
        mock_client.chat.completions.parse = MagicMock(return_value=mock_response)

        with patch("backend.providers.openai.run_sync_in_executor", new=mock_executor):
            await provider.generate_structured(
                prompt="No images",
                response_model=TestResponse,
                images=None,
            )

        call_kwargs = mock_client.chat.completions.parse.call_args[1]
        user_message = call_kwargs["messages"][0]
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
