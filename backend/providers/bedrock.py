"""AWS Bedrock LLM provider implementation using the Converse API."""

import base64
import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.models.extended import ImageContent
from backend.models.usage import UsageRecord
from backend.providers._recovery import (
    VALIDATION_RESTATE_INSTRUCTION,
    coerce_tool_input,
    describe_validation_errors,
)
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderTimeoutError,
    ProviderTransientError,
    is_openai_family_model,
    run_sync_in_executor,
    strip_markdown_fences,
)
from backend.providers.usage import as_token_count, record_usage


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_AUTO_BUMP = 16384
_MAX_RETRIES = 2

# Module-level schema cache — deterministic per class, computed once.
_schema_cache: dict[type, dict] = {}

# Bedrock model IDs use dotted-path format: e.g.
#   us.anthropic.claude-sonnet-4-20250514-v1:0
#   amazon.nova-pro-v1:0
# Plain API format IDs (e.g. "claude-sonnet-4-20250514") do not contain a "."
# and are rejected with a clear error so the user gets actionable feedback.
_BEDROCK_ID_HINT = (
    "Bedrock model IDs use provider-namespaced format, e.g. "
    "'us.anthropic.claude-sonnet-4-20250514-v1:0' or 'amazon.nova-pro-v1:0'. "
    "Plain API model IDs (e.g. 'claude-sonnet-4-20250514') are not accepted."
)

# System instruction sent with `toolChoice: auto`, for models that reject
# forced tool choice (see BedrockProvider's docstring).
_AUTO_TOOL_INSTRUCTION = (
    "Answer by calling the `respond` tool exactly once, with your complete answer as its "
    "input. Do not answer in plain text."
)

# Sent once, as an extra system message, when a model calls `respond` with
# an empty input — reported on Claude 5.x (Opus 5.5, Sonnet 5, Haiku 5.5,
# Fable 5.1) in the 10-09 Bedrock session, cause unconfirmed (no
# converse.jsonl from that session to check stop reasons / token counts
# against; a plausible guess is thinking tokens eating the output budget
# before any tool-input tokens are written). Restating the instruction
# gives the retry a better shot than an identical blind retry.
_EMPTY_TOOL_INPUT_RESTATE_INSTRUCTION = (
    "Your previous call to the `respond` tool had an empty or incomplete input. Call it "
    "again with the complete input, including every required field, conforming to the schema."
)

# Model-ID substrings (case-insensitive) that take images, absent an
# override. Conservative default: only the families known to accept vision
# input on Bedrock. "amazon.nova-micro" is deliberately excluded — it's
# text-only, unlike the other Nova sizes. Everything else (gpt-oss, Qwen,
# DeepSeek, Llama text variants, etc.) is treated as text-only until
# BEDROCK_IMAGE_MODELS says otherwise.
_DEFAULT_IMAGE_MODEL_HINTS = (
    "anthropic.claude",
    "amazon.nova-lite",
    "amazon.nova-pro",
    "amazon.nova-premier",
)

# Bedrock Converse `stopReason` values that mean the model refused to answer
# or a guardrail/content filter intervened — not a format failure, and not
# worth retrying with the same prompt. "refusal" mirrors the direct
# Anthropic API's stop_reason for a Claude 5.x safety refusal; unconfirmed
# whether Bedrock Converse uses the same string for Claude on Bedrock (check
# the diagnostic run's converse.jsonl), but matching it costs nothing if not.
_REFUSAL_STOP_REASONS = frozenset({"content_filtered", "guardrail_intervened", "refusal"})


class BedrockProvider:
    """AWS Bedrock provider using the Converse API for structured output.

    Supports Claude on Bedrock and Amazon Nova models. Models that do not
    support tool use at all (e.g. Llama, Mistral) are not supported.

    Structured output forces the `respond` tool (`toolChoice: {"tool": ...}`).
    Claude Opus 5.5 / Sonnet 5.5 / Fable 5.1 reject forced tool choice with a
    400 (and on Bedrock it also requires thinking disabled, which those
    models can't do), so on that rejection the instance switches to
    `toolChoice: {"auto": {}}` plus a system instruction naming the tool, and
    accepts a JSON text answer if the model replies in text instead.

    `effort` is opt-in and family-specific: Claude models get
    `output_config.effort` (ANTHROPIC_EFFORT); OpenAI-family models take
    OPENAI_REASONING_EFFORT in `additionalModelRequestFields`: GPT-6 Sol/Luna
    as the nested `reasoning.effort` (live-verified 2026-10-17; the flat
    `reasoning_effort` is an unknown parameter there), gpt-oss as the flat
    `reasoning_effort`. A model that rejects it falls back the same lazy way
    `temperature` and forced tool choice do — one failed call, then never
    sent again for the rest of this instance's calls.

    `temperature` is never sent to OpenAI reasoning models (every OpenAI
    family model except gpt-oss): GPT-6 on Bedrock rejects it whatever the
    effort ("This model doesn't support the temperature field"). gpt-oss
    keeps it unless a reasoning effort other than `none` is set.

    Authentication follows the standard boto3 credential chain:
    environment variables → ~/.aws/credentials → IAM roles. No explicit
    access key parameters are accepted; use AWS_PROFILE or IAM roles instead.
    """

    def __init__(
        self,
        model: str,
        region: str = "",
        profile: str = "",
        image_models: list[str] | None = None,
        effort: str | None = None,
    ):
        """Initialise Bedrock provider.

        Args:
            model: Bedrock model ID in provider-namespaced format.
            region: AWS region for the Bedrock endpoint.
            profile: AWS named profile (empty string = default credential chain).
            image_models: Optional override (BEDROCK_IMAGE_MODELS) of which
                model-ID substrings accept images, replacing the built-in
                default (Claude and the vision-capable Nova sizes) rather
                than extending it.
            effort: Optional `output_config.effort` level (low/medium/high/xhigh/max),
                sent via `additionalModelRequestFields`. None sends nothing,
                which is the model's default. Non-Claude models, and some
                Claude models, may reject it — see the class docstring.

        Raises:
            ImportError: If boto3 is not installed.
            ValueError: If model ID uses plain API format instead of Bedrock format.
        """
        try:
            import boto3
            import botocore.config
        except ImportError:
            raise ImportError(
                "boto3 is required for the Bedrock provider. "
                "Install with: pip install paranoid-cli[bedrock]"
            )

        if "." not in model:
            raise ValueError(f"Invalid Bedrock model ID {model!r}. {_BEDROCK_ID_HINT}")

        self._model = model
        self._region = region
        self._image_models = [h.lower() for h in (image_models or [])]
        # Some model families reject `temperature` outright with a 400
        # ValidationException rather than accepting/ignoring it (see the
        # direct Anthropic provider's identical fallback). Detected lazily on
        # first call and cached per instance so later calls skip the doomed
        # round-trip entirely.
        self._temperature_unsupported = False
        # Same lazy detection for forced tool choice (see the class docstring).
        self._forced_tool_choice_unsupported = False
        # Same lazy detection for `effort` (see the class docstring).
        self._effort = effort
        self._effort_unsupported = False

        session = boto3.Session(profile_name=profile or None)
        # Omit region_name when empty so boto3's own resolution runs
        # (AWS_DEFAULT_REGION → profile → instance metadata service).
        client_kwargs: dict = {}
        if region:
            client_kwargs["region_name"] = region
        self._client = session.client(
            "bedrock-runtime",
            **client_kwargs,
            config=botocore.config.Config(
                read_timeout=240,
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )

    def _record_usage(self, response: dict) -> None:
        """Record this response's token usage from the Converse API's `usage` block."""
        usage = response.get("usage", {})
        record_usage(
            UsageRecord(
                provider=self.name,
                model=self._model,
                input_tokens=as_token_count(usage.get("inputTokens")),
                output_tokens=as_token_count(usage.get("outputTokens")),
                cache_read_tokens=as_token_count(usage.get("cacheReadInputTokens")),
                cache_write_tokens=as_token_count(usage.get("cacheWriteInputTokens")),
            )
        )

    @property
    def name(self) -> str:
        return "bedrock"

    @property
    def model(self) -> str:
        return self._model

    @property
    def supports_images(self) -> bool:
        """Per-model image support: Claude and Nova IDs by default, or — when
        an image_models override was passed in — only models matching it."""
        model_lower = self._model.lower()
        if self._image_models:
            return any(hint in model_lower for hint in self._image_models)
        return any(hint in model_lower for hint in _DEFAULT_IMAGE_MODEL_HINTS)

    @property
    def effort(self) -> str | None:
        """The `output_config.effort` level actually in effect — None if
        never set, or if the model rejected it (see `_effort_unsupported`)."""
        return None if self._effort_unsupported else self._effort

    async def _converse(self, inference_config: dict[str, Any], **kwargs: Any) -> dict:
        """Call `bedrock-runtime.converse`, retrying once without `temperature`
        and/or once without `effort` if this model rejects either outright
        (a `ValidationException` rather than accepting/silently ignoring it —
        mirrors the direct Anthropic provider's `_create_message` fallback).
        Each rejection flips a per-instance flag, so a later call for the
        same instance skips the doomed round-trip entirely; recursion here
        is bounded by those two flags (at most one extra attempt per flag)."""
        config = dict(inference_config)
        if self._temperature_unsupported:
            config.pop("temperature", None)

        # Decided independently of effort so that the retry after an effort
        # rejection doesn't reintroduce a temperature the model also rejects.
        if _is_openai_reasoning_model(self._model):
            config.pop("temperature", None)

        call_kwargs = dict(kwargs)
        if self._effort and not self._effort_unsupported:
            if is_openai_family_model(self._model):
                effort_field: dict[str, Any] = (
                    {"reasoning": {"effort": self._effort}}
                    if _is_openai_reasoning_model(self._model)
                    else {"reasoning_effort": self._effort}
                )
                if self._effort != "none":
                    # gpt-oss rejects temperature once reasoning is on; omit it
                    # up front instead of burning a failed call.
                    config.pop("temperature", None)
            else:
                effort_field = {"output_config": {"effort": self._effort}}
            call_kwargs["additionalModelRequestFields"] = {
                **call_kwargs.get("additionalModelRequestFields", {}),
                **effort_field,
            }

        try:
            return await run_sync_in_executor(
                self._client.converse, inferenceConfig=config, **call_kwargs
            )
        except Exception as e:
            if not self._temperature_unsupported and _is_temperature_deprecated_error(e):
                self._temperature_unsupported = True
                logger.warning(
                    "Model %s rejects the `temperature` parameter — omitting it "
                    "for the rest of this provider instance's calls",
                    self._model,
                )
                return await self._converse(inference_config, **kwargs)
            if self._effort and not self._effort_unsupported and _is_effort_unsupported_error(e):
                self._effort_unsupported = True
                logger.warning(
                    "Model %s rejects the `effort` parameter — omitting it "
                    "for the rest of this provider instance's calls",
                    self._model,
                )
                return await self._converse(inference_config, **kwargs)
            raise

    async def _converse_structured(
        self,
        inference_config: dict[str, Any],
        tools: list[dict],
        *,
        extra_system: list[dict] | None = None,
        **kwargs: Any,
    ) -> dict:
        """`_converse` with the `respond` tool, forced unless this model has
        already rejected forced tool choice. On that rejection, retry once
        with `auto` + an instruction and remember it for later calls.

        `extra_system` is an additional system message the caller wants on
        this attempt only (e.g. restating the instruction after an empty
        tool-input response) — it's combined with the auto-tool-choice
        instruction when that fallback is already active, never replacing it.
        """
        if not self._forced_tool_choice_unsupported:
            try:
                return await self._converse(
                    inference_config,
                    toolConfig={"tools": tools, "toolChoice": {"tool": {"name": "respond"}}},
                    **({"system": extra_system} if extra_system else {}),
                    **kwargs,
                )
            except Exception as e:
                if not _is_forced_tool_choice_error(e):
                    raise
                self._forced_tool_choice_unsupported = True
                logger.warning(
                    "Model %s rejects forced tool choice — using auto tool choice with an "
                    "instruction for the rest of this provider instance's calls",
                    self._model,
                )
        return await self._converse(
            inference_config,
            toolConfig={"tools": tools, "toolChoice": {"auto": {}}},
            system=[{"text": _AUTO_TOOL_INSTRUCTION}, *(extra_system or [])],
            **kwargs,
        )

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        images: list[ImageContent] | None = None,
        shared_context: str | None = None,
    ) -> T:
        """Generate structured output via Bedrock Converse API with toolConfig.

        Auto-bumps max_tokens 2x on truncation, up to _MAX_AUTO_BUMP, max _MAX_RETRIES retries.
        """
        try:
            if response_model not in _schema_cache:
                _schema_cache[response_model] = response_model.model_json_schema()
            schema = _schema_cache[response_model]

            tools = [
                {
                    "toolSpec": {
                        "name": "respond",
                        "description": (
                            "Respond with structured JSON conforming to the provided schema."
                        ),
                        "inputSchema": {"json": schema},
                    }
                }
            ]

            content_blocks = _build_content_blocks(prompt, images, shared_context)
            budget = max_tokens or 4096
            last_error: ProviderError | None = None
            restate_instruction: list[dict] | None = None

            for attempt in range(1 + _MAX_RETRIES):
                response = await self._converse_structured(
                    {"maxTokens": budget, "temperature": temperature},
                    tools,
                    extra_system=restate_instruction,
                    modelId=self._model,
                    messages=[{"role": "user", "content": content_blocks}],
                )
                restate_instruction = None
                self._record_usage(response)

                stop_reason = response.get("stopReason", "")

                if stop_reason in _REFUSAL_STOP_REASONS:
                    raise ProviderRefusalError(
                        provider=self.name,
                        message=f"Bedrock refused the request (stopReason={stop_reason!r})",
                    )

                if stop_reason == "max_tokens" and budget < _MAX_AUTO_BUMP:
                    old = budget
                    budget = min(budget * 2, _MAX_AUTO_BUMP)
                    logger.warning(
                        "Bedrock output truncated (max_tokens) at %d, bumping to %d (attempt %d/%d)",
                        old,
                        budget,
                        attempt + 1,
                        1 + _MAX_RETRIES,
                    )
                    continue

                # Extract tool_use response block
                output_content = response.get("output", {}).get("message", {}).get("content", [])
                tool_block = next(
                    (b for b in output_content if b.get("toolUse")),
                    None,
                )
                if tool_block is not None:
                    data = tool_block["toolUse"]["input"]
                    # Reported on Claude 5.x (see
                    # _EMPTY_TOOL_INPUT_RESTATE_INSTRUCTION): the tool is
                    # called but its input is `{}` — every required field
                    # missing, not just malformed. stopReason isn't
                    # max_tokens here (that case is already handled above,
                    # and is the right fix if it turns out this is really
                    # truncation under another name), so the fix is a fresh
                    # attempt with the instruction restated, not a budget
                    # bump.
                    if not data and schema.get("required") and stop_reason != "max_tokens":
                        last_error = ProviderError(
                            provider=self.name,
                            message=(
                                f"Bedrock returned an empty tool input (stopReason={stop_reason!r})"
                            ),
                        )
                        if attempt < _MAX_RETRIES:
                            logger.warning(
                                "Bedrock model %s called the respond tool with an empty input; "
                                "retrying with the instruction restated (attempt %d/%d)",
                                self._model,
                                attempt + 1,
                                1 + _MAX_RETRIES,
                            )
                            restate_instruction = [{"text": _EMPTY_TOOL_INPUT_RESTATE_INSTRUCTION}]
                            continue
                        raise last_error
                else:
                    # No tool call: accept the text if it's the JSON we asked
                    # for, under any tool choice. Some models (GPT-OSS, Qwen in
                    # the 10-11 bench) accept a forced toolChoice and then
                    # answer in prose with stopReason end_turn, rather than
                    # rejecting it the way _is_forced_tool_choice_error() catches.
                    data = _json_from_text_blocks(output_content)
                    if data is None:
                        last_error = ProviderError(
                            provider=self.name,
                            message=f"Bedrock returned no tool_use block (stopReason={stop_reason!r})",
                        )
                        if attempt < _MAX_RETRIES:
                            if not self._forced_tool_choice_unsupported:
                                # Ignoring forced tool choice is treated like
                                # rejecting it: auto + instruction from here on.
                                self._forced_tool_choice_unsupported = True
                                logger.warning(
                                    "Bedrock model %s ignored forced tool choice and answered "
                                    "in text - using auto tool choice for the rest of this "
                                    "provider instance's calls (attempt %d/%d)",
                                    self._model,
                                    attempt + 1,
                                    1 + _MAX_RETRIES,
                                )
                            else:
                                logger.warning(
                                    "Bedrock model %s answered without calling the respond "
                                    "tool; retrying (attempt %d/%d)",
                                    self._model,
                                    attempt + 1,
                                    1 + _MAX_RETRIES,
                                )
                            continue
                        raise last_error

                data = coerce_tool_input(data, schema, model=self._model)

                try:
                    return response_model.model_validate(data)
                except ValidationError as e:
                    last_error = ProviderError(
                        provider=self.name,
                        message=f"Failed to validate structured output: {e}",
                        original_error=e,
                    )
                    if attempt < _MAX_RETRIES:
                        # Retry even at the budget cap (the old loop gave up
                        # there), and restate the instruction: a malformed
                        # value isn't truncation, which stopReason max_tokens
                        # already handles above. Still bounded by _MAX_RETRIES.
                        budget = min(budget * 2, _MAX_AUTO_BUMP)
                        problems = describe_validation_errors(e)
                        logger.warning(
                            "Bedrock model %s returned a tool input that failed validation "
                            "(%s); retrying with the instruction restated (attempt %d/%d)",
                            self._model,
                            problems.replace("\n", " "),
                            attempt + 1,
                            1 + _MAX_RETRIES,
                        )
                        restate_instruction = [
                            {"text": VALIDATION_RESTATE_INSTRUCTION.format(problems=problems)}
                        ]
                        continue
                    raise last_error

            if last_error:
                raise last_error
            raise ProviderError(  # pragma: no cover
                provider=self.name,
                message="Auto-bump retries exhausted without producing valid output",
            )

        except ProviderError:
            raise
        except Exception as e:
            raise _map_boto_error(self.name, e) from e

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate plain text via Bedrock Converse API (no toolConfig)."""
        try:
            response = await self._converse(
                {"maxTokens": max_tokens or 4096, "temperature": temperature},
                modelId=self._model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            self._record_usage(response)
            output_content = response.get("output", {}).get("message", {}).get("content", [])
            text_block = next((b for b in output_content if "text" in b), None)
            if text_block is None:
                raise ProviderError(provider=self.name, message="Bedrock returned no text block")
            return text_block["text"]

        except ProviderError:
            raise
        except Exception as e:
            raise _map_boto_error(self.name, e) from e

    async def __aenter__(self) -> "BedrockProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def _build_content_blocks(
    prompt: str,
    images: list[ImageContent] | None,
    shared_context: str | None,
) -> list[dict]:
    """Build Converse API content block list.

    Order: images → shared_context → prompt (same stable-prefix convention as Anthropic provider).
    """
    blocks: list[dict] = []

    if images:
        # With more than one image, a short "Image i of n" label precedes
        # each (matches the Anthropic path); a single image is unaffected.
        multiple = len(images) > 1
        for i, img in enumerate(images, start=1):
            if multiple:
                blocks.append({"text": f"Image {i} of {len(images)}: {img.source}"})
            # Decode base64 to bytes — Bedrock Converse expects raw bytes in image.source.bytes
            raw_bytes = base64.b64decode(img.data)
            fmt = img.media_type.split("/")[-1]  # "image/png" → "png"
            blocks.append({"image": {"format": fmt, "source": {"bytes": raw_bytes}}})

    if shared_context:
        blocks.append({"text": shared_context})

    blocks.append({"text": prompt})
    return blocks


def _is_forced_tool_choice_error(exc: Exception) -> bool:
    """True when `exc` is a Bedrock `ValidationException` about tool choice,
    e.g. Claude's "tool_choice: type "tool" and "any" are not supported for
    this model." (duck-typed like `_is_temperature_deprecated_error`)."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    if response.get("Error", {}).get("Code") != "ValidationException":
        return False
    message = str(exc).lower()
    return any(term in message for term in ("tool_choice", "toolchoice", "tool choice"))


def _json_from_text_blocks(content: list[dict]) -> Any | None:
    """Parse the response's text blocks as JSON (fences stripped), or None."""
    text = "".join(b["text"] for b in content if isinstance(b.get("text"), str)).strip()
    if not text:
        return None
    try:
        return json.loads(strip_markdown_fences(text))
    except json.JSONDecodeError:
        return None


def _is_temperature_deprecated_error(exc: Exception) -> bool:
    """True when `exc` is a botocore `ClientError` (duck-typed via `.response`
    so this module never needs an unconditional `botocore` import — boto3 is
    an optional extra) whose Bedrock `ValidationException` complains about
    the `temperature` parameter, mirroring the direct Anthropic provider's
    `_is_temperature_deprecated_error`."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    if response.get("Error", {}).get("Code") != "ValidationException":
        return False
    message = str(exc).lower()
    return "temperature" in message and any(
        phrase in message
        for phrase in (
            "deprecated",
            "not supported",
            "unsupported",
            # GPT-6 on Bedrock: "This model doesn't support the temperature field."
            "doesn't support",
            "does not support",
        )
    )


def _is_openai_reasoning_model(model_id: str) -> bool:
    """True for OpenAI-family Bedrock models that reject `temperature`
    outright (GPT-6 Sol/Luna and later) — every OpenAI model except the
    open-weight gpt-oss, which accepts it while reasoning is off."""
    return is_openai_family_model(model_id) and "gpt-oss" not in model_id.lower()


def _is_effort_unsupported_error(exc: Exception) -> bool:
    """True when `exc` is a botocore `ClientError` whose Bedrock
    `ValidationException` complains about the `effort` /
    `additionalModelRequestFields.output_config` / `reasoning` field,
    mirroring the direct Anthropic provider's `_is_effort_unsupported_error`."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    if response.get("Error", {}).get("Code") != "ValidationException":
        return False
    message = str(exc).lower()
    return "effort" in message or "output_config" in message or "reasoning" in message


_CLIENT_ERROR_CLASSES: dict[str, type[ProviderError]] = {
    "AccessDeniedException": ProviderAuthError,
    "ThrottlingException": ProviderRateLimitError,
    # AWS documents this as a 429 ("the model isn't ready to serve
    # inference requests") that should be retried, same as throttling.
    "ModelNotReadyException": ProviderRateLimitError,
    "ModelTimeoutException": ProviderTimeoutError,
    "ServiceUnavailableException": ProviderTransientError,
    "InternalServerException": ProviderTransientError,
}


def _map_boto_error(provider_name: str, exc: Exception) -> ProviderError:
    """Map botocore/boto3 exceptions to ProviderError subclasses."""
    try:
        import importlib

        bce = importlib.import_module("botocore.exceptions")

        error_cls: type[ProviderError] = ProviderError
        message = str(exc)
        if isinstance(exc, bce.NoCredentialsError):
            error_cls = ProviderAuthError
            message = "No AWS credentials found. Configure via environment, ~/.aws/credentials, or IAM role."
        elif isinstance(exc, (bce.ReadTimeoutError, bce.ConnectTimeoutError)):
            error_cls = ProviderTimeoutError
            message = f"Bedrock request timed out: {exc}"
        elif isinstance(exc, bce.EndpointConnectionError):
            error_cls = ProviderTransientError
            message = f"Could not reach Bedrock endpoint: {exc}"
        elif isinstance(exc, bce.ClientError):
            code = exc.response["Error"]["Code"]
            if code in _CLIENT_ERROR_CLASSES:
                error_cls = _CLIENT_ERROR_CLASSES[code]
            else:
                # Not one of the codes we know by name — fall back to the HTTP
                # status so an unlisted 5xx (a new AWS error code, a transient
                # gateway response) still gets retried instead of permanently
                # disabling fast routing.
                http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                error_cls = (
                    ProviderTransientError if http_status and http_status >= 500 else ProviderError
                )
            message = f"Bedrock error [{code}]: {exc.response['Error'].get('Message', '')}"
        elif isinstance(exc, bce.HTTPClientError):
            # Covers ConnectionClosedError, ResponseStreamingError and any
            # other client-side HTTP failure not already matched above by a
            # more specific type (timeouts, endpoint connection).
            error_cls = ProviderTransientError
            message = f"Bedrock connection error: {exc}"
        return error_cls(provider=provider_name, message=message, original_error=exc)

    except ImportError:
        pass

    return ProviderError(provider=provider_name, message=str(exc), original_error=exc)
