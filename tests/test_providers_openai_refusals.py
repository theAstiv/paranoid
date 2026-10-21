"""OpenAI content filter and refusals (bug-bash plan §5.6, run order item 25).

The pipeline's fallbacks (fast → main, LLM → rule engine) catch ProviderError,
and the run's refusal_count counts ProviderRefusalError. These check that
OpenAI's two "won't answer" outcomes arrive as those types. The SDK client is
mocked; no network.
"""

from unittest.mock import MagicMock, patch

import pytest
from openai import ContentFilterFinishReasonError
from pydantic import BaseModel

from backend.providers.base import ProviderError, ProviderRefusalError
from backend.providers.openai import OpenAIProvider


class _Answer(BaseModel):
    value: str


def _provider_whose_parse(side_effect=None, return_value=None) -> OpenAIProvider:
    with patch("backend.providers.openai.OpenAI") as mock_openai:
        client = MagicMock()
        client.chat.completions.parse.side_effect = side_effect
        client.chat.completions.parse.return_value = return_value
        mock_openai.return_value = client
        return OpenAIProvider(model="gpt-4.1", api_key="test-key")


@pytest.mark.asyncio
async def test_content_filter_stop_is_a_provider_refusal():
    provider = _provider_whose_parse(side_effect=ContentFilterFinishReasonError())
    with pytest.raises(ProviderRefusalError):
        await provider.generate_structured(prompt="hi", response_model=_Answer)


@pytest.mark.asyncio
async def test_a_model_refusal_is_a_provider_refusal():
    response = MagicMock()
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    response.choices[0].message.parsed = None
    response.choices[0].message.refusal = "I can't help with that."
    provider = _provider_whose_parse(return_value=response)
    with pytest.raises(ProviderRefusalError):
        await provider.generate_structured(prompt="hi", response_model=_Answer)


@pytest.mark.asyncio
async def test_no_parsed_output_without_a_refusal_stays_a_plain_provider_error():
    response = MagicMock()
    response.usage = MagicMock(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    response.choices[0].message.parsed = None
    response.choices[0].message.refusal = None
    provider = _provider_whose_parse(return_value=response)
    with pytest.raises(ProviderError) as info:
        await provider.generate_structured(prompt="hi", response_model=_Answer)
    assert not isinstance(info.value, ProviderRefusalError)
