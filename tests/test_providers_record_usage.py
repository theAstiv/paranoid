"""Per-provider usage-field tests (week 4a-1, follow-up to review feedback).

tests/test_providers_usage.py only exercises the shared collection code
(record_usage/collect_usage/summarize_usage) — nothing there calls a real
provider's ``_record_usage()``, so a wrong SDK field name would silently
report zero tokens forever. These tests mock each provider's SDK client to
return a response with known usage fields and assert the exact UsageRecord
that ends up in a ``collect_usage()`` scope, matching the field names
verified against the installed SDKs (anthropic 0.86, openai 2.29,
botocore 1.39 Converse) during the 4a-1 spike.
"""

import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from backend.models.usage import UsageRecord
from backend.providers.anthropic import AnthropicProvider
from backend.providers.base import ProviderError
from backend.providers.bedrock import BedrockProvider
from backend.providers.ollama import OllamaProvider
from backend.providers.openai import OpenAIProvider
from backend.providers.usage import collect_usage


class _SimpleModel(BaseModel):
    value: str


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_records_usage_from_response():
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        mock_response = MagicMock()
        mock_response.stop_reason = "end_turn"
        mock_response.content = [MagicMock(text=json.dumps({"value": "x"}))]
        mock_response.usage = MagicMock(
            input_tokens=150,
            output_tokens=75,
            cache_creation_input_tokens=10,
            cache_read_input_tokens=20,
        )

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        assert records == [
            UsageRecord(
                provider="anthropic",
                model="claude-sonnet-5",
                input_tokens=150,
                output_tokens=75,
                cache_read_tokens=20,
                cache_write_tokens=10,
            )
        ]


@pytest.mark.asyncio
async def test_anthropic_counts_every_auto_bump_attempt():
    """A truncated first attempt (stop_reason=max_tokens) still billed its
    tokens before the retry — both attempts must be recorded."""
    with patch("backend.providers.anthropic.Anthropic") as mock_anthropic:
        truncated = MagicMock()
        truncated.stop_reason = "max_tokens"
        truncated.content = [MagicMock(text="")]
        truncated.usage = MagicMock(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        complete = MagicMock()
        complete.stop_reason = "end_turn"
        complete.content = [MagicMock(text=json.dumps({"value": "x"}))]
        complete.usage = MagicMock(
            input_tokens=100,
            output_tokens=120,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [truncated, complete]
        mock_anthropic.return_value = mock_client

        provider = AnthropicProvider(model="claude-sonnet-5", api_key="test-key")
        with collect_usage() as records:
            await provider.generate_structured(
                prompt="hi", response_model=_SimpleModel, max_tokens=512
            )

        assert len(records) == 2
        assert [r.output_tokens for r in records] == [50, 120]


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_records_usage_and_splits_cached_tokens_out_of_input():
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        mock_message = MagicMock()
        mock_message.parsed = _SimpleModel(value="x")
        mock_message.refusal = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(
            prompt_tokens=200,
            completion_tokens=80,
            prompt_tokens_details=MagicMock(cached_tokens=50),
        )

        mock_client = MagicMock()
        mock_client.chat.completions.parse.return_value = mock_response
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4.1-mini", api_key="test-key")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        # prompt_tokens (200) includes the 50 cached tokens on OpenAI; input_tokens
        # must report only the uncached 150, with the 50 moved to cache_read_tokens.
        assert records == [
            UsageRecord(
                provider="openai",
                model="gpt-4.1-mini",
                input_tokens=150,
                output_tokens=80,
                cache_read_tokens=50,
            )
        ]


@pytest.mark.asyncio
async def test_openai_records_zero_usage_row_when_usage_missing():
    """No usage object on the response still counts as a call, matching the
    other three providers' as_token_count()-based zero-fill — otherwise
    OpenAI's call count would undercount relative to the others."""
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        mock_message = MagicMock()
        mock_message.parsed = _SimpleModel(value="x")
        mock_message.refusal = None
        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None

        mock_client = MagicMock()
        mock_client.chat.completions.parse.return_value = mock_response
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4.1-mini", api_key="test-key")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        assert records == [UsageRecord(provider="openai", model="gpt-4.1-mini")]


@pytest.mark.asyncio
async def test_openai_records_usage_from_truncated_response_before_raising():
    """LengthFinishReasonError.completion.usage reflects the truncated
    attempt — those tokens were billed and must be recorded even though the
    call ultimately fails (after exhausting auto-bump retries)."""
    from openai import LengthFinishReasonError

    with patch("backend.providers.openai.OpenAI") as mock_openai:
        completions = []
        for _ in range(3):
            completion = MagicMock()
            completion.usage = MagicMock(
                prompt_tokens=100, completion_tokens=200, prompt_tokens_details=None
            )
            completions.append(completion)

        mock_client = MagicMock()
        mock_client.chat.completions.parse.side_effect = [
            LengthFinishReasonError(completion=c) for c in completions
        ]
        mock_openai.return_value = mock_client

        provider = OpenAIProvider(model="gpt-4o", api_key="test-key")
        with collect_usage() as records, pytest.raises(ProviderError):
            await provider.generate_structured(
                prompt="hi", response_model=_SimpleModel, max_tokens=100
            )

        assert len(records) == 3
        assert all(r.output_tokens == 200 for r in records)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_records_usage_from_eval_counts():
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps({"value": "x"}),
            "done_reason": "stop",
            "prompt_eval_count": 60,
            "eval_count": 40,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3.1:8b")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        assert records == [
            UsageRecord(provider="ollama", model="llama3.1:8b", input_tokens=60, output_tokens=40)
        ]


@pytest.mark.asyncio
async def test_ollama_records_usage_with_missing_eval_counts_as_zero():
    """Some Ollama builds omit prompt_eval_count/eval_count entirely —
    must not crash, and must record a zero-filled call."""
    with patch("backend.providers.ollama.httpx.AsyncClient") as mock_client_class:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": json.dumps({"value": "x"}),
            "done_reason": "stop",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client_class.return_value = mock_client

        provider = OllamaProvider(model="llama3.1:8b")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        assert records == [UsageRecord(provider="ollama", model="llama3.1:8b")]


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------


def _make_tool_response(data: dict) -> dict:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"content": [{"toolUse": {"name": "respond", "input": data}}]}},
        "usage": {
            "inputTokens": 300,
            "outputTokens": 90,
            "totalTokens": 390,
            "cacheReadInputTokens": 25,
            "cacheWriteInputTokens": 15,
        },
    }


@pytest.mark.asyncio
async def test_bedrock_records_usage_from_converse_response():
    with patch.dict(
        sys.modules,
        {"boto3": MagicMock(), "botocore": MagicMock(), "botocore.config": MagicMock()},
    ):
        mock_boto3 = sys.modules["boto3"]
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_client.converse.return_value = _make_tool_response({"value": "x"})
        mock_session.client.return_value = mock_client
        mock_boto3.Session.return_value = mock_session

        provider = BedrockProvider(model="us.anthropic.claude-sonnet-5-v1:0")
        with collect_usage() as records:
            await provider.generate_structured(prompt="hi", response_model=_SimpleModel)

        assert records == [
            UsageRecord(
                provider="bedrock",
                model="us.anthropic.claude-sonnet-5-v1:0",
                input_tokens=300,
                output_tokens=90,
                cache_read_tokens=25,
                cache_write_tokens=15,
            )
        ]
