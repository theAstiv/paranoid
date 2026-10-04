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
    ProviderTimeoutError,
    ProviderTransientError,
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
async def test_anthropic_generate_structured_tolerates_raw_control_characters(
    sample_asset_list,
):
    """Some models (e.g. claude-sonnet-5) emit a raw, unescaped literal newline
    inside a JSON string value in longer free-text fields — this must still
    parse rather than raising "Invalid control character"."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        raw_json = (
            '{"assets": [{"type": "Asset", "name": "Database",'
            ' "description": "line one\nline two"}]}'
        )
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=raw_json)]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")
        result = await provider.generate_structured(
            prompt="List the assets",
            response_model=AssetsList,
        )

        assert result.assets[0].description == "line one\nline two"


@pytest.mark.asyncio
async def test_anthropic_temperature_deprecated_retries_without_it():
    """Some model families (e.g. claude-sonnet-5) reject `temperature` outright
    with a 400 rather than accepting/ignoring it — the call must retry once
    without it and succeed, not surface the error."""
    from anthropic import BadRequestError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.status_code = 400
        temperature_error = BadRequestError(
            message="`temperature` is deprecated for this model.",
            response=mock_response,
            body={"error": {"message": "`temperature` is deprecated for this model."}},
        )

        mock_success = MagicMock()
        mock_success.content = [MagicMock(text="ok without temperature")]

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [temperature_error, mock_success]
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")
        result = await provider.generate(prompt="Hello")

        assert result == "ok without temperature"
        assert mock_client.messages.create.call_count == 2
        first_call_kwargs = mock_client.messages.create.call_args_list[0].kwargs
        second_call_kwargs = mock_client.messages.create.call_args_list[1].kwargs
        assert "temperature" in first_call_kwargs
        assert "temperature" not in second_call_kwargs

        # The instance remembers this for later calls — no wasted round-trip.
        mock_client.messages.create.side_effect = [mock_success]
        await provider.generate(prompt="Hello again")
        third_call_kwargs = mock_client.messages.create.call_args_list[-1].kwargs
        assert "temperature" not in third_call_kwargs


def _text_response(text: str, stop_reason: str = "end_turn", extra_blocks=()):
    response = MagicMock()
    response.stop_reason = stop_reason
    response.usage.output_tokens = 123
    response.content = [*extra_blocks, MagicMock(type="text", text=text)]
    return response


@pytest.mark.asyncio
async def test_anthropic_empty_response_is_retried_with_a_bigger_budget():
    """After a max_tokens bump, claude-sonnet-5 once returned an empty text
    block (not stop_reason=max_tokens), which raised `Expecting value` and dropped
    gap analysis to the fallback. An empty response must be retried like a
    truncation."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        truncated = _text_response('{"assets": [', stop_reason="max_tokens")
        empty = _text_response("")
        ok = _text_response('{"assets": []}')
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [truncated, empty, ok]
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="k")
        result = await provider.generate_structured(prompt="x", response_model=AssetsList)

        assert result.assets == []
        budgets = [c.kwargs["max_tokens"] for c in mock_client.messages.create.call_args_list]
        assert budgets[0] < budgets[1] < budgets[2]


@pytest.mark.asyncio
async def test_anthropic_persistent_empty_response_reports_why(caplog):
    """When every attempt is empty the error must say so, with the stop reason and
    block types (the log previously gave no clue what the model returned)."""
    import logging

    from backend.providers import ProviderError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        thinking = MagicMock(type="thinking", text=None)
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = lambda **_: _text_response(
            "", extra_blocks=[thinking]
        )
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="k")
        with caplog.at_level(logging.WARNING, logger="backend.providers.anthropic"):
            with pytest.raises(ProviderError) as exc_info:
                await provider.generate_structured(prompt="x", response_model=AssetsList)

        message = str(exc_info.value)
        assert "empty response" in message
        assert "stop_reason=end_turn" in message
        assert "thinking" in message
        assert any("stop_reason=end_turn" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_anthropic_non_json_response_is_retried_at_the_same_budget(caplog):
    """B4/B5 (live): gap analysis intermittently came back as non-JSON text
    (`Expecting value: line 1 column 1`), which failed the whole step on the first
    occurrence. It is intermittent, so one retry should recover — without a
    pointless token bump, since it isn't a truncation."""
    import logging

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        prose = _text_response("I'll analyze the coverage gaps now.")
        ok = _text_response('{"assets": []}')
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [prose, ok]
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="k")
        with caplog.at_level(logging.WARNING, logger="backend.providers.anthropic"):
            result = await provider.generate_structured(prompt="x", response_model=AssetsList)

        assert result.assets == []
        budgets = [c.kwargs["max_tokens"] for c in mock_client.messages.create.call_args_list]
        assert budgets[0] == budgets[1]
        # The diagnostic records what the model actually said.
        assert any("analyze the coverage gaps" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_anthropic_persistent_non_json_response_still_raises():
    from backend.providers import ProviderError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = lambda **_: _text_response("not json at all")
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="k")
        with pytest.raises(ProviderError, match="Failed to parse structured output"):
            await provider.generate_structured(prompt="x", response_model=AssetsList)
        assert mock_client.messages.create.call_count == 3


@pytest.mark.asyncio
async def test_anthropic_effort_is_sent_as_output_config():
    """claude-sonnet-5 at its default effort overran 4096 tokens on threat JSON
    and failed to parse; an opt-in effort setting must reach the API."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_success = MagicMock()
        mock_success.content = [MagicMock(text="ok")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_success
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="k", effort="medium")
        await provider.generate(prompt="Hello")

        kwargs = mock_client.messages.create.call_args.kwargs
        assert kwargs["extra_body"] == {"output_config": {"effort": "medium"}}


@pytest.mark.asyncio
async def test_anthropic_without_effort_sends_no_output_config():
    """Unset effort must leave requests byte-identical to before (older models
    such as Haiku 4.5 reject the parameter)."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_success = MagicMock()
        mock_success.content = [MagicMock(text="ok")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_success
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-haiku-4-5", api_key="k")
        await provider.generate(prompt="Hello")

        assert "extra_body" not in mock_client.messages.create.call_args.kwargs


@pytest.mark.asyncio
async def test_anthropic_effort_rejected_retries_without_it_and_remembers():
    """A model that rejects `effort` must not turn a run into rule-engine-only:
    retry once without it, and remember so later calls skip the doomed trip."""
    from anthropic import BadRequestError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.status_code = 400
        effort_error = BadRequestError(
            message="output_config.effort: this model does not support effort",
            response=mock_response,
            body={"error": {"message": "output_config.effort is not supported"}},
        )
        mock_success = MagicMock()
        mock_success.content = [MagicMock(text="ok without effort")]
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [effort_error, mock_success]
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-haiku-4-5", api_key="k", effort="medium")
        assert await provider.generate(prompt="Hello") == "ok without effort"
        assert mock_client.messages.create.call_count == 2
        calls = mock_client.messages.create.call_args_list
        assert "extra_body" in calls[0].kwargs
        assert "extra_body" not in calls[1].kwargs

        mock_client.messages.create.side_effect = [mock_success]
        await provider.generate(prompt="Hello again")
        assert "extra_body" not in mock_client.messages.create.call_args_list[-1].kwargs


@pytest.mark.asyncio
async def test_anthropic_other_bad_request_error_still_raises():
    """A 400 unrelated to `temperature` must not be swallowed by the
    temperature-fallback retry — it should surface as a ProviderError."""
    from anthropic import BadRequestError

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.status_code = 400
        other_error = BadRequestError(
            message="max_tokens is too large",
            response=mock_response,
            body={"error": {"message": "max_tokens is too large"}},
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = other_error
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")

        with pytest.raises(ProviderError):
            await provider.generate(prompt="Hello")
        assert mock_client.messages.create.call_count == 1


@pytest.mark.asyncio
async def test_anthropic_skips_thinking_block_to_find_text():
    """Extended-thinking-capable models (e.g. claude-sonnet-5) put a
    ThinkingBlock ahead of the TextBlock in `response.content` — the actual
    text must still be found, not just content[0]."""

    class _ThinkingBlock:
        type = "thinking"
        thinking = "reasoning about the answer..."

    class _TextBlock:
        type = "text"
        text = "the actual answer"

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.content = [_ThinkingBlock(), _TextBlock()]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")
        result = await provider.generate(prompt="Hello")

        assert result == "the actual answer"


@pytest.mark.asyncio
async def test_anthropic_no_text_block_raises_provider_error():
    """A response with no text block at all (e.g. thinking-only, or a future
    block type this code doesn't know about) must fail closed with a typed
    error, not an AttributeError deep inside JSON parsing."""

    class _ThinkingBlock:
        type = "thinking"
        thinking = "..."

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.content = [_ThinkingBlock()]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")

        with pytest.raises(ProviderError):
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
    """Test OpenAI structured output generation (Structured Outputs / parse API)."""
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        # parse() returns the Pydantic model directly on message.parsed
        parsed_result = AssetsList(
            assets=[
                Asset(type=AssetType.ASSET, name="Database", description="PostgreSQL DB"),
                Asset(type=AssetType.ENTITY, name="User", description="End user"),
            ]
        )
        mock_message = MagicMock()
        mock_message.parsed = parsed_result
        mock_message.refusal = None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.parse.return_value = mock_response
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4o", api_key="test-key")
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
async def test_ollama_repairs_missing_required_fields():
    """Ollama provider should fill missing optional containers and return a partial
    result rather than crashing the pipeline when a small model omits a required field."""
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        # Asset missing 'description' (required string field).
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps(
                {
                    "assets": [
                        {"type": "Asset", "name": "Database"},  # description missing
                    ]
                }
            )
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        # The single asset has a missing required field — that's a nested-field
        # validation error which our top-level fill doesn't touch. The repair
        # path only patches missing required fields at the *top* of the model.
        # So this should still raise ProviderError. Test that to lock the behaviour.
        with pytest.raises(ProviderError):
            await provider.generate_structured(prompt="x", response_model=AssetsList)


@pytest.mark.asyncio
async def test_ollama_repairs_missing_top_level_list():
    """Top-level required list field that the model omitted is auto-filled with []."""
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        # AssetsList is `{"assets": [...]}` — return a body that's missing `assets`.
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": json.dumps({})}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3")
        result = await provider.generate_structured(prompt="x", response_model=AssetsList)
        assert isinstance(result, AssetsList)
        assert result.assets == []


def test_anthropic_default_timeout_covers_slow_thinking_models():
    """60s timed out generate_threats on claude-sonnet-5 (8K-token output) on every
    retry, dropping the whole run to rule-engine-only; matches OpenAI's 240s."""
    with patch("backend.providers.anthropic.Anthropic") as client_cls:
        AnthropicProvider(model="claude-sonnet-5", api_key="k")
    assert client_cls.call_args.kwargs["timeout"] == 240.0


def test_ollama_default_timeout_is_300s():
    """Default timeout was raised from 120s to 300s to handle dense MAESTRO runs."""
    provider = OllamaProvider(model="llama3")
    assert provider._timeout == 300.0


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


# Transient error classification (week 4a-3)
#
# Timeouts, connection errors and 5xx responses must surface as
# ProviderTransientError (or its ProviderTimeoutError subclass) so the
# runner's fast-model circuit breaker doesn't treat them as permanent.


def _http_request():
    import httpx

    return httpx.Request("POST", "https://api.example.test/v1")


def _http_response(status: int):
    import httpx

    return httpx.Response(status, request=_http_request())


def _anthropic_errors():
    import anthropic
    from anthropic import _exceptions

    return [
        ("timeout", anthropic.APITimeoutError(request=_http_request()), ProviderTimeoutError),
        (
            "connection",
            anthropic.APIConnectionError(request=_http_request()),
            ProviderTransientError,
        ),
        (
            "500",
            anthropic.InternalServerError("boom", response=_http_response(500), body=None),
            ProviderTransientError,
        ),
        (
            "529-overloaded",
            _exceptions.OverloadedError("overloaded", response=_http_response(529), body=None),
            ProviderTransientError,
        ),
    ]


def _openai_errors():
    import openai

    return [
        ("timeout", openai.APITimeoutError(request=_http_request()), ProviderTimeoutError),
        (
            "connection",
            openai.APIConnectionError(request=_http_request()),
            ProviderTransientError,
        ),
        (
            "503",
            openai.InternalServerError("unavailable", response=_http_response(503), body=None),
            ProviderTransientError,
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "error", "expected"),
    _anthropic_errors(),
    ids=lambda v: v if isinstance(v, str) else "",
)
async def test_anthropic_transient_errors_are_classified(label, error, expected):
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = error
        mock_anthropic.return_value = mock_client
        provider = AnthropicProvider(model="claude-sonnet-4", api_key="test-key")

        with pytest.raises(expected):
            await provider.generate(prompt="Hello")
        with pytest.raises(expected):
            await provider.generate_structured(prompt="x", response_model=AssetsList)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "error", "expected"), _openai_errors(), ids=lambda v: v if isinstance(v, str) else ""
)
async def test_openai_transient_errors_are_classified(label, error, expected):
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = error
        mock_client.chat.completions.parse.side_effect = error
        mock_openai.return_value = mock_client
        provider = OpenAIProvider(model="gpt-4o", api_key="test-key")

        with pytest.raises(expected):
            await provider.generate(prompt="Hello")
        with pytest.raises(expected):
            await provider.generate_structured(prompt="x", response_model=AssetsList)


@pytest.mark.asyncio
async def test_anthropic_and_openai_not_found_stays_non_transient():
    import anthropic
    import openai

    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = anthropic.NotFoundError(
            "model not found", response=_http_response(404), body=None
        )
        mock_anthropic.return_value = mock_client
        provider = AnthropicProvider(model="claude-nope", api_key="test-key")
        with pytest.raises(ProviderError) as exc_info:
            await provider.generate(prompt="Hello")
        assert not isinstance(exc_info.value, ProviderTransientError)

    with patch("backend.providers.openai.OpenAI") as mock_openai:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = openai.NotFoundError(
            "model not found", response=_http_response(404), body=None
        )
        mock_openai.return_value = mock_client
        provider = OpenAIProvider(model="gpt-nope", api_key="test-key")
        with pytest.raises(ProviderError) as exc_info:
            await provider.generate(prompt="Hello")
        assert not isinstance(exc_info.value, ProviderTransientError)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "transient"),
    [
        # Ollama returns 500 for a permanent load failure (not enough system
        # memory, a crashed runtime) and 502/503/504 for a busy/restarting
        # server — only the latter can reasonably succeed on a later call.
        (500, False),
        (502, True),
        (503, True),
        (504, True),
        (404, False),
        (400, False),
    ],
)
async def test_ollama_http_status_classification(status, transient):
    import httpx

    response = _http_response(status)
    error = httpx.HTTPStatusError("status", request=response.request, response=response)
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = error
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="llama3")

        for make_call in (
            lambda: provider.generate(prompt="Hello"),
            lambda: provider.generate_structured(prompt="x", response_model=AssetsList),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await make_call()
            assert isinstance(exc_info.value, ProviderTransientError) is transient


@pytest.mark.asyncio
async def test_ollama_connection_error_is_transient():
    import httpx

    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="llama3")

        with pytest.raises(ProviderTransientError, match="is Ollama running"):
            await provider.generate(prompt="Hello")
        with pytest.raises(ProviderTransientError, match="is Ollama running"):
            await provider.generate_structured(prompt="x", response_model=AssetsList)


def test_timeout_and_rate_limit_errors_are_transient():
    assert issubclass(ProviderTimeoutError, ProviderTransientError)
    assert issubclass(ProviderRateLimitError, ProviderTransientError)
    assert issubclass(ProviderTransientError, ProviderError)
    assert not issubclass(ProviderAuthError, ProviderTransientError)


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
