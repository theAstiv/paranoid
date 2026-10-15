"""OpenAIProvider reasoning_effort support and lazy parameter fallbacks.

The SDK is mocked at the boundary, as in tests/test_providers.py.
"""

from unittest.mock import MagicMock, patch

import pytest
from openai import BadRequestError
from pydantic import BaseModel

from backend.providers.openai import OpenAIProvider


class _Out(BaseModel):
    value: str


def _parse_response(value: str = "ok") -> MagicMock:
    message = MagicMock()
    message.parsed = _Out(value=value)
    message.refusal = None
    response = MagicMock()
    response.choices = [MagicMock(message=message)]
    response.usage = None
    return response


def _bad_request(message: str) -> BadRequestError:
    http = MagicMock()
    http.status_code = 400
    return BadRequestError(message=message, response=http, body={"error": {"message": message}})


def _provider(mock_openai, parse_results, **kwargs) -> tuple[OpenAIProvider, MagicMock]:
    client = MagicMock()
    client.chat.completions.parse.side_effect = parse_results
    mock_openai.return_value = client
    return OpenAIProvider(model="gpt-6-luna", api_key="k", **kwargs), client


async def _structured(provider: OpenAIProvider) -> _Out:
    return await provider.generate_structured("p", _Out, temperature=0.2, max_tokens=1000)


@pytest.mark.asyncio
async def test_without_effort_the_request_is_unchanged():
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [_parse_response()])
        await _structured(provider)

    kwargs = client.chat.completions.parse.call_args.kwargs
    assert kwargs["temperature"] == 0.2
    assert kwargs["max_tokens"] == 1000
    assert "reasoning_effort" not in kwargs
    assert "max_completion_tokens" not in kwargs
    assert provider.effort is None


@pytest.mark.asyncio
async def test_effort_none_sends_effort_and_keeps_temperature():
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [_parse_response()], reasoning_effort="none")
        await _structured(provider)

    kwargs = client.chat.completions.parse.call_args.kwargs
    assert kwargs["reasoning_effort"] == "none"
    assert kwargs["temperature"] == 0.2
    assert provider.effort == "none"


@pytest.mark.asyncio
async def test_effort_medium_sends_effort_and_omits_temperature():
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [_parse_response()], reasoning_effort="medium")
        await _structured(provider)

    kwargs = client.chat.completions.parse.call_args.kwargs
    assert kwargs["reasoning_effort"] == "medium"
    assert "temperature" not in kwargs


@pytest.mark.asyncio
async def test_rejected_effort_is_retried_without_it_and_remembered():
    error = _bad_request("Unsupported parameter: 'reasoning_effort' is not supported")
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(
            mock_openai,
            [error, _parse_response("first"), _parse_response("second")],
            reasoning_effort="medium",
        )
        assert (await _structured(provider)).value == "first"
        assert (await _structured(provider)).value == "second"

    calls = client.chat.completions.parse.call_args_list
    assert len(calls) == 3
    assert "reasoning_effort" in calls[0].kwargs
    assert "reasoning_effort" not in calls[1].kwargs
    assert "reasoning_effort" not in calls[2].kwargs  # remembered
    assert calls[1].kwargs["temperature"] == 0.2  # temperature is valid again
    assert provider.effort is None


@pytest.mark.asyncio
async def test_rejected_temperature_is_dropped_and_remembered():
    error = _bad_request("Unsupported parameter: 'temperature' is not supported with this model")
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [error, _parse_response(), _parse_response()])
        await _structured(provider)
        await _structured(provider)

    calls = client.chat.completions.parse.call_args_list
    assert "temperature" in calls[0].kwargs
    assert "temperature" not in calls[1].kwargs
    assert "temperature" not in calls[2].kwargs


@pytest.mark.asyncio
async def test_max_tokens_rejection_switches_to_max_completion_tokens():
    error = _bad_request(
        "Unsupported parameter: 'max_tokens' is not supported with this model. "
        "Use 'max_completion_tokens' instead."
    )
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [error, _parse_response(), _parse_response()])
        await _structured(provider)
        await _structured(provider)

    calls = client.chat.completions.parse.call_args_list
    assert calls[0].kwargs["max_tokens"] == 1000
    assert "max_tokens" not in calls[1].kwargs
    assert calls[1].kwargs["max_completion_tokens"] == 1000
    assert calls[2].kwargs["max_completion_tokens"] == 1000


@pytest.mark.asyncio
async def test_all_three_rejections_in_one_call_still_succeed():
    errors = [
        _bad_request("'reasoning_effort' is not supported"),
        _bad_request("'temperature' is not supported"),
        _bad_request("'max_tokens' is not supported; use 'max_completion_tokens'"),
    ]
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(
            mock_openai, [*errors, _parse_response()], reasoning_effort="none"
        )
        result = await _structured(provider)

    assert result.value == "ok"
    final = client.chat.completions.parse.call_args.kwargs
    assert set(final) >= {"max_completion_tokens"}
    assert "temperature" not in final
    assert "reasoning_effort" not in final


@pytest.mark.asyncio
async def test_unrelated_bad_request_is_not_swallowed():
    from backend.providers.base import ProviderError

    error = _bad_request("Invalid schema for response_format 'Out'")
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        provider, client = _provider(mock_openai, [error])
        with pytest.raises(ProviderError):
            await _structured(provider)

    assert client.chat.completions.parse.call_count == 1


@pytest.mark.asyncio
async def test_generate_plain_text_sends_effort_too():
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="hi"))], usage=None
        )
        mock_openai.return_value = client
        provider = OpenAIProvider(model="gpt-6-luna", api_key="k", reasoning_effort="low")
        assert await provider.generate("hello", temperature=0.2, max_tokens=50) == "hi"

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "low"
    assert "temperature" not in kwargs
