"""Tests for the AWS Bedrock provider (backend/providers/bedrock.py).

All tests mock boto3 — no AWS credentials or network access required.
"""

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import botocore.exceptions as _bce
import pytest
from pydantic import BaseModel

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderTransientError,
    create_provider,
)
from backend.providers.bedrock import BedrockProvider, _build_content_blocks, _map_boto_error


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


def _make_client_error(
    code: str, message: str = "test error", http_status: int | None = None
) -> Any:
    """Create a botocore ClientError with the given error code and, when a
    caller wants to test status-code-based classification for a code that
    isn't in the explicit lookup table, an HTTP status on ResponseMetadata."""
    import botocore.exceptions

    response: dict = {"Error": {"Code": code, "Message": message}}
    if http_status is not None:
        response["ResponseMetadata"] = {"HTTPStatusCode": http_status}
    return botocore.exceptions.ClientError(response, "Converse")


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


@pytest.mark.asyncio
async def test_bedrock_generate_structured_retries_without_temperature():
    """A ValidationException complaining about `temperature` retries once
    without it, then the flag persists for later calls on the same instance
    (skipping the doomed round-trip entirely)."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client

    calls: list[dict] = []
    # Built before entering the patched-sys.modules block below: `_make_client_error`
    # does `import botocore.exceptions` internally, which needs the *real*
    # `botocore` package attribute chain intact to resolve to the real
    # `ClientError` class — not the mock that replaces `sys.modules["botocore"]`
    # for the provider's own imports.
    temperature_error = _make_client_error(
        "ValidationException", "temperature is not supported for this model"
    )

    def _converse(**kwargs):
        calls.append(kwargs)
        if "temperature" in kwargs["inferenceConfig"]:
            raise temperature_error
        return _make_tool_response({"value": "ok", "count": 1})

    mock_client.converse.side_effect = _converse

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        result = await provider.generate_structured("test", _SimpleModel)

    assert result.value == "ok"
    assert len(calls) == 2
    assert "temperature" in calls[0]["inferenceConfig"]
    assert "temperature" not in calls[1]["inferenceConfig"]

    # Second call on the same instance: the flag is already set, so it skips
    # straight to the no-temperature call — no repeated failing attempt.
    result2 = await provider.generate_structured("test again", _SimpleModel)
    assert result2.value == "ok"
    assert len(calls) == 3
    assert "temperature" not in calls[2]["inferenceConfig"]


@pytest.mark.asyncio
async def test_bedrock_generate_retries_without_temperature():
    """The plain-text generate() path gets the same retry-without-temperature
    fallback as generate_structured()."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client

    calls: list[dict] = []
    temperature_error = _make_client_error("ValidationException", "temperature is deprecated")

    def _converse(**kwargs):
        calls.append(kwargs)
        if "temperature" in kwargs["inferenceConfig"]:
            raise temperature_error
        return _make_text_response("hello world")

    mock_client.converse.side_effect = _converse

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="amazon.nova-pro-v1:0")
        result = await provider.generate("test prompt")

    assert result == "hello world"
    assert len(calls) == 2
    assert "temperature" not in calls[1]["inferenceConfig"]


@pytest.mark.asyncio
async def test_bedrock_non_temperature_validation_error_still_raises():
    """A ValidationException unrelated to `temperature` is not swallowed by
    the retry — it must surface as a real error, not a silent success."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.side_effect = _make_client_error("ValidationException", "invalid model id")

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
        with pytest.raises(ProviderError):
            await provider.generate_structured("test", _SimpleModel)

    assert mock_client.converse.call_count == 1


# ---------------------------------------------------------------------------
# Forced tool choice fallback (Opus 5.5 / Sonnet 5.5 / Fable 5.1)
# ---------------------------------------------------------------------------

_OPUS_55 = "us.anthropic.claude-opus-5-5"
_FORCED_TOOL_CHOICE_MESSAGE = 'tool_choice: type "tool" and "any" are not supported for this model.'


def _patched_modules(mock_boto3: MagicMock) -> dict:
    return {
        "boto3": mock_boto3,
        "botocore": MagicMock(),
        "botocore.config": MagicMock(),
        "botocore.exceptions": _bce,
    }


def _mock_boto3_with_client(mock_client: MagicMock) -> MagicMock:
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    return mock_boto3


@pytest.mark.asyncio
async def test_bedrock_forced_tool_choice_rejection_falls_back_to_auto():
    """A ValidationException about tool_choice retries once with
    `toolChoice: auto` + a system instruction, and the instance remembers it
    so later calls skip the doomed forced attempt."""
    mock_client = MagicMock()
    calls: list[dict] = []
    tool_choice_error = _make_client_error("ValidationException", _FORCED_TOOL_CHOICE_MESSAGE)

    def _converse(**kwargs):
        calls.append(kwargs)
        if "tool" in kwargs["toolConfig"]["toolChoice"]:
            raise tool_choice_error
        return _make_tool_response({"value": "ok", "count": 1})

    mock_client.converse.side_effect = _converse

    with patch.dict(sys.modules, _patched_modules(_mock_boto3_with_client(mock_client))):
        provider = BedrockProvider(model=_OPUS_55)
        result = await provider.generate_structured("test", _SimpleModel)

        assert result.value == "ok"
        assert len(calls) == 2
        assert calls[0]["toolConfig"]["toolChoice"] == {"tool": {"name": "respond"}}
        assert "system" not in calls[0]
        assert calls[1]["toolConfig"]["toolChoice"] == {"auto": {}}
        assert "respond" in calls[1]["system"][0]["text"]

        result2 = await provider.generate_structured("again", _SimpleModel)

    assert result2.value == "ok"
    assert len(calls) == 3
    assert calls[2]["toolConfig"]["toolChoice"] == {"auto": {}}


@pytest.mark.asyncio
async def test_bedrock_auto_tool_choice_accepts_json_text_answer():
    """Under auto tool choice a model may answer in text; a fenced JSON
    answer that matches the schema is accepted without another call."""
    mock_client = MagicMock()
    tool_choice_error = _make_client_error("ValidationException", _FORCED_TOOL_CHOICE_MESSAGE)
    mock_client.converse.side_effect = [
        tool_choice_error,
        _make_text_response('```json\n{"value": "from text", "count": 2}\n```'),
    ]

    with patch.dict(sys.modules, _patched_modules(_mock_boto3_with_client(mock_client))):
        provider = BedrockProvider(model=_OPUS_55)
        result = await provider.generate_structured("test", _SimpleModel)

    assert result.value == "from text"
    assert result.count == 2
    assert mock_client.converse.call_count == 2


@pytest.mark.asyncio
async def test_bedrock_auto_tool_choice_retries_a_prose_answer():
    """A prose answer (no tool call, not JSON) under auto tool choice is
    retried rather than failing the step outright."""
    mock_client = MagicMock()
    tool_choice_error = _make_client_error("ValidationException", _FORCED_TOOL_CHOICE_MESSAGE)
    mock_client.converse.side_effect = [
        tool_choice_error,
        _make_text_response("**Threat Name**: something in prose"),
        _make_tool_response({"value": "ok", "count": 1}),
    ]

    with patch.dict(sys.modules, _patched_modules(_mock_boto3_with_client(mock_client))):
        provider = BedrockProvider(model=_OPUS_55)
        result = await provider.generate_structured("test", _SimpleModel)

    assert result.value == "ok"
    assert mock_client.converse.call_count == 3


@pytest.mark.asyncio
async def test_bedrock_text_answer_under_forced_tool_choice_still_errors():
    """While forced tool choice is in effect, a text-only answer is still an
    error — the JSON-from-text path is only for auto tool choice."""
    mock_client = MagicMock()
    mock_client.converse.return_value = _make_text_response('{"value": "x", "count": 1}')

    with patch.dict(sys.modules, _patched_modules(_mock_boto3_with_client(mock_client))):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderError, match="no tool_use block"):
            await provider.generate_structured("test", _SimpleModel)

    assert mock_client.converse.call_count == 1


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


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_make_client_error("ServiceUnavailableException"), ProviderTransientError),
        (_make_client_error("InternalServerException"), ProviderTransientError),
        (_make_client_error("ThrottlingException"), ProviderRateLimitError),
        (_make_client_error("ModelTimeoutException"), ProviderTimeoutError),
        (_bce.ReadTimeoutError(endpoint_url="https://bedrock.test"), ProviderTimeoutError),
        (_bce.ConnectTimeoutError(endpoint_url="https://bedrock.test"), ProviderTimeoutError),
        (_bce.EndpointConnectionError(endpoint_url="https://bedrock.test"), ProviderTransientError),
        (_bce.ConnectionClosedError(endpoint_url="https://bedrock.test"), ProviderTransientError),
        (_bce.ResponseStreamingError(error=RuntimeError("stream broke")), ProviderTransientError),
        (_make_client_error("ModelNotReadyException"), ProviderRateLimitError),
        # Not in the explicit code table — classified by HTTP status instead.
        (_make_client_error("InternalFailure", http_status=502), ProviderTransientError),
        (_make_client_error("UnmappedException", http_status=503), ProviderTransientError),
    ],
    ids=lambda v: type(v).__name__ if isinstance(v, Exception) else v.__name__,
)
def test_map_boto_error_classifies_transient_failures(error, expected):
    mapped = _map_boto_error("bedrock", error)
    assert isinstance(mapped, expected)
    assert isinstance(mapped, ProviderTransientError)


@pytest.mark.parametrize(
    "error",
    [
        _make_client_error("ValidationException"),
        _make_client_error("ResourceNotFoundException"),
        _make_client_error("AccessDeniedException"),
        # No ResponseMetadata at all — must not crash, must not be treated
        # as transient by default.
        _make_client_error("SomeOtherException"),
        _make_client_error("SomeOtherException", http_status=400),
    ],
    ids=lambda e: (
        f"{e.response['Error']['Code']}-{e.response.get('ResponseMetadata', {}).get('HTTPStatusCode')}"
    ),
)
def test_map_boto_error_keeps_permanent_failures_non_transient(error):
    mapped = _map_boto_error("bedrock", error)
    assert isinstance(mapped, ProviderError)
    assert not isinstance(mapped, ProviderTransientError)


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


# ---------------------------------------------------------------------------
# _build_content_blocks (vision / multi-diagram)
# ---------------------------------------------------------------------------


def test_build_content_blocks_single_image_unchanged():
    image = ImageContent(data="aGVsbG8=", media_type="image/png", source="arch.png")
    blocks = _build_content_blocks("Describe this", [image], None)

    # No label block for a single image: image + prompt text = 2 blocks.
    assert len(blocks) == 2
    assert "image" in blocks[0]
    assert blocks[1] == {"text": "Describe this"}


def test_build_content_blocks_multiple_images_interleave_labels():
    images = [
        ImageContent(data="aGVsbG8=", media_type="image/png", source="1.png"),
        ImageContent(data="d29ybGQ=", media_type="image/jpeg", source="2.jpg"),
    ]
    blocks = _build_content_blocks("Compare diagrams", images, None)

    # label1 + image1 + label2 + image2 + prompt text = 5 blocks.
    assert len(blocks) == 5
    assert blocks[0] == {"text": "Image 1 of 2: 1.png"}
    assert "image" in blocks[1]
    assert blocks[2] == {"text": "Image 2 of 2: 2.jpg"}
    assert "image" in blocks[3]
    assert blocks[4] == {"text": "Compare diagrams"}


def test_build_content_blocks_without_images():
    blocks = _build_content_blocks("No images here", None, None)
    assert blocks == [{"text": "No images here"}]


def test_build_content_blocks_with_shared_context():
    blocks = _build_content_blocks("dynamic prompt", None, "stable shared context")
    assert blocks == [{"text": "stable shared context"}, {"text": "dynamic prompt"}]


# ---------------------------------------------------------------------------
# supports_images (per-model capability, PR A)
# ---------------------------------------------------------------------------


def _make_bedrock_provider(model: str, image_models: list[str] | None = None) -> BedrockProvider:
    mock_boto3 = MagicMock()
    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        return BedrockProvider(model=model, image_models=image_models)


@pytest.mark.parametrize(
    "model",
    [
        "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "amazon.nova-pro-v1:0",
        "us.amazon.nova-lite-v1:0",
    ],
)
def test_bedrock_supports_images_default_claude_and_nova(model):
    provider = _make_bedrock_provider(model)
    assert provider.supports_images is True


@pytest.mark.parametrize(
    "model",
    [
        "openai.gpt-oss-120b-1:0",
        "qwen.qwen3-32b-v1:0",
        "deepseek.r1-v1:0",
        # Nova Micro is text-only, unlike the other Nova sizes.
        "amazon.nova-micro-v1:0",
    ],
)
def test_bedrock_supports_images_default_text_only(model):
    provider = _make_bedrock_provider(model)
    assert provider.supports_images is False


def test_bedrock_image_models_override_restricts_to_listed_models():
    """BEDROCK_IMAGE_MODELS, when set, replaces the built-in default — a
    model that would default to text-only can be opted in, and a Claude
    model not on the list is opted back out, without a code change."""
    opted_in = _make_bedrock_provider("openai.gpt-oss-120b-1:0", image_models=["gpt-oss"])
    assert opted_in.supports_images is True

    opted_out = _make_bedrock_provider(
        "us.anthropic.claude-sonnet-4-20250514-v1:0", image_models=["gpt-oss"]
    )
    assert opted_out.supports_images is False


# ---------------------------------------------------------------------------
# Refusals (PR A): content_filtered / guardrail_intervened -> ProviderRefusalError
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stop_reason", ["content_filtered", "guardrail_intervened", "refusal"])
@pytest.mark.asyncio
async def test_bedrock_refusal_stop_reason_raises_refusal_error(stop_reason):
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.return_value = {
        "stopReason": stop_reason,
        "output": {"message": {"content": []}},
    }

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderRefusalError):
            await provider.generate_structured("test prompt", _SimpleModel)


@pytest.mark.asyncio
async def test_bedrock_refusal_is_not_retried():
    """A refusal is non-transient: it must surface on the first attempt, not
    burn through the auto-bump retry budget."""
    mock_boto3 = MagicMock()
    mock_session = MagicMock()
    mock_client = MagicMock()
    mock_boto3.Session.return_value = mock_session
    mock_session.client.return_value = mock_client
    mock_client.converse.return_value = {
        "stopReason": "content_filtered",
        "output": {"message": {"content": []}},
    }

    with patch.dict(
        sys.modules, {"boto3": mock_boto3, "botocore": MagicMock(), "botocore.config": MagicMock()}
    ):
        provider = BedrockProvider(model="us.anthropic.claude-sonnet-4-20250514-v1:0")
        with pytest.raises(ProviderRefusalError):
            await provider.generate_structured("test prompt", _SimpleModel)

    assert mock_client.converse.call_count == 1
