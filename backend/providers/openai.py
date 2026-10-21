"""OpenAI LLM provider implementation."""

import logging
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel

from backend.models.extended import ImageContent
from backend.models.usage import UsageRecord
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderRefusalError,
    map_sdk_api_error,
    run_sync_in_executor,
)
from backend.providers.usage import as_token_count, record_usage


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Auto-bump constants — mirror the Anthropic provider.
# OpenAI's hard ceilings differ by model (gpt-4o: 16 384, gpt-4.1: 32 768,
# GPT-6: far higher), but our retry logic just doubles the *requested* budget
# up to this cap; the model will still cap at its own maximum.
_MAX_AUTO_BUMP = 32768
_MAX_RETRIES = 2


class OpenAIProvider:
    """OpenAI GPT provider with structured output support.

    Usage as async context manager (recommended):
        async with OpenAIProvider(model="gpt-4", api_key="...") as provider:
            result = await provider.generate_structured(...)

    The OpenAI sync SDK client doesn't require explicit closing, but the
    context manager interface is provided for consistency with the Protocol.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        max_retries: int = 3,
        timeout: float = 240.0,
        reasoning_effort: str | None = None,
    ):
        """Initialize OpenAI provider.

        Args:
            model: Model identifier (e.g., 'gpt-4', 'gpt-4-turbo')
            api_key: OpenAI API key
            base_url: Custom API base URL (for Azure or compatible APIs)
            max_retries: Number of retry attempts for failed requests
            timeout: Request timeout in seconds
            reasoning_effort: Optional `reasoning_effort` level (none/low/medium/
                high/xhigh/max) for GPT-6-class reasoning models. None sends
                nothing. Any level other than "none" also omits `temperature`,
                which those models reject once reasoning is on. A model that
                rejects the parameter loses it for the rest of this instance's
                calls (see `_call`).
        """
        self._model = model
        # Parameters a model may reject with a 400, detected lazily on the first
        # rejection and remembered, so later calls skip the doomed round-trip
        # (the same pattern the Anthropic and Bedrock providers use).
        self._effort = reasoning_effort
        self._effort_unsupported = False
        self._temperature_unsupported = False
        self._use_completion_tokens = False
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    def _record_usage(self, usage) -> None:
        """Record this response's token usage. ``prompt_tokens`` includes any
        cached portion on OpenAI, so it's split out into cache_read_tokens to
        match the other providers' "uncached input" meaning.

        Still records a (zero-token) call when ``usage`` is missing, so the
        call count stays consistent with the other three providers, which
        all record a zero-filled UsageRecord via ``as_token_count()``'s
        None-handling rather than skipping the call outright.
        """
        if usage is None:
            record_usage(UsageRecord(provider=self.name, model=self._model))
            return
        cached = as_token_count(
            getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        )
        prompt_tokens = as_token_count(getattr(usage, "prompt_tokens", None))
        record_usage(
            UsageRecord(
                provider=self.name,
                model=self._model,
                input_tokens=max(prompt_tokens - cached, 0),
                output_tokens=as_token_count(getattr(usage, "completion_tokens", None)),
                cache_read_tokens=cached,
            )
        )

    @property
    def name(self) -> str:
        """Provider name."""
        return "openai"

    @property
    def model(self) -> str:
        """Model identifier."""
        return self._model

    @property
    def supports_images(self) -> bool:
        """Vision-capable GPT-4o-class models support images."""
        return True

    @property
    def effort(self) -> str | None:
        """The `reasoning_effort` level actually in effect — None if never set,
        or if the model rejected it (see `_effort_unsupported`)."""
        return None if self._effort_unsupported else self._effort

    def _request_params(self, budget: int | None, temperature: float) -> dict:
        """Sampling/budget parameters for one request, minus anything this
        model is already known to reject."""
        params: dict = {}
        if budget is not None:
            key = "max_completion_tokens" if self._use_completion_tokens else "max_tokens"
            params[key] = budget
        effort = None if self._effort_unsupported else self._effort
        if effort:
            params["reasoning_effort"] = effort
        # Reasoning models reject temperature unless effort is "none".
        reasoning_on = bool(effort) and effort != "none"
        if not self._temperature_unsupported and not reasoning_on:
            params["temperature"] = temperature
        return params

    def _drop_rejected_param(self, e: BadRequestError, sent: dict) -> bool:
        """Flip the flag for the parameter a 400 complains about. True if the
        caller should retry; False means a real error.

        `sent` is what the failed request carried: a rejection of a parameter
        this call sent is retriable even if a concurrent call already flipped
        the flag (BB-32), and the flag is flipped and logged only once."""
        message = str(e).lower()
        if "reasoning_effort" in message and "reasoning_effort" in sent:
            if not self._effort_unsupported:
                self._effort_unsupported = True
                logger.warning(
                    "Model %s rejects `reasoning_effort` — omitting it for the rest of "
                    "this provider instance's calls",
                    self._model,
                )
            return True
        if "temperature" in message and "temperature" in sent:
            if not self._temperature_unsupported:
                self._temperature_unsupported = True
                logger.warning(
                    "Model %s rejects `temperature` — omitting it for the rest of "
                    "this provider instance's calls",
                    self._model,
                )
            return True
        if "max_tokens" in message and "max_completion_tokens" in message and "max_tokens" in sent:
            if not self._use_completion_tokens:
                self._use_completion_tokens = True
                logger.warning(
                    "Model %s requires `max_completion_tokens` — switching for the rest of "
                    "this provider instance's calls",
                    self._model,
                )
            return True
        return False

    async def _call(self, func, *, budget: int | None, temperature: float, **kwargs):
        """Call a chat-completions method, retrying without a parameter the model
        rejects. Each rejection flips a per-instance flag, so the number of
        retries is bounded by the number of flags."""
        while True:
            params = self._request_params(budget, temperature)
            try:
                return await run_sync_in_executor(func, model=self._model, **params, **kwargs)
            except BadRequestError as e:
                if not self._drop_rejected_param(e, params):
                    raise

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        images: list[ImageContent] | None = None,
        shared_context: str | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        Supports vision API for PNG/JPG images via image_url content blocks.

        **Auto-bump:** When the model hits its output token ceiling
        (``LengthFinishReasonError``), the method automatically retries with
        2x the token budget, up to ``_MAX_AUTO_BUMP`` and ``_MAX_RETRIES``
        additional attempts.

        Note: OpenAI JSON mode + vision is only supported on gpt-4o and gpt-4o-mini.
        Models like gpt-4-vision-preview do not support JSON mode with images.

        shared_context is prepended to the user prompt text. OpenAI does not support
        prompt caching via content blocks, so the benefit here is semantic consistency
        with the Anthropic path rather than a cost reduction.
        """
        try:
            # Build user message content (images + text)
            user_content = []

            # Add images as data URIs. With more than one image, a short
            # "Image i of n" label precedes each (matches the Anthropic
            # path); a single image is unaffected.
            if images:
                multiple = len(images) > 1
                for i, img in enumerate(images, start=1):
                    if multiple:
                        user_content.append(
                            {"type": "text", "text": f"Image {i} of {len(images)}: {img.source}"}
                        )
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{img.media_type};base64,{img.data}"},
                        }
                    )

            # Prepend shared_context to prompt text (no native caching on OpenAI)
            full_user_text = f"{shared_context}\n\n{prompt}" if shared_context else prompt
            user_content.append({"type": "text", "text": full_user_text})

            # ── Auto-bump retry loop ──────────────────────────────────────
            budget = max_tokens  # may be None (model default)
            last_length_error: ProviderError | None = None

            for attempt in range(1 + _MAX_RETRIES):
                try:
                    # Use Structured Outputs (Aug 2024+) — the SDK converts
                    # the Pydantic model to a strict JSON schema and enforces
                    # it server-side.  Requires gpt-4o-2024-08-06 or later.
                    response = await self._call(
                        self._client.chat.completions.parse,
                        budget=budget,
                        temperature=temperature,
                        response_format=response_model,
                        messages=[
                            {"role": "user", "content": user_content},
                        ],
                    )

                    self._record_usage(response.usage)
                    parsed = response.choices[0].message.parsed
                    if parsed is None:
                        refusal = response.choices[0].message.refusal
                        if refusal:
                            raise ProviderRefusalError(
                                provider=self.name,
                                message=f"Model refused to answer: {refusal}",
                            )
                        raise ProviderError(
                            provider=self.name,
                            message="Model returned no parsed output",
                        )
                    return parsed

                except ContentFilterFinishReasonError as e:
                    # An OpenAIError, not an APIError: without this it escapes every
                    # `except ProviderError` fallback as a raw SDK exception.
                    raise ProviderRefusalError(
                        provider=self.name,
                        message="Response blocked by OpenAI's content filter",
                        original_error=e,
                    ) from e

                except LengthFinishReasonError as e:
                    # Model hit its output token ceiling before completing JSON.
                    # The truncated completion still billed tokens — record them.
                    self._record_usage(e.completion.usage)
                    current = budget or 4096
                    if attempt < _MAX_RETRIES and current < _MAX_AUTO_BUMP:
                        old = current
                        budget = min(current * 2, _MAX_AUTO_BUMP)
                        logger.warning(
                            "OpenAI output truncated (LengthFinishReasonError) "
                            "at %d tokens, auto-bumping to %d (attempt %d/%d)",
                            old,
                            budget,
                            attempt + 1,
                            1 + _MAX_RETRIES,
                        )
                        last_length_error = ProviderError(
                            provider=self.name,
                            message=(
                                "Model hit the output token ceiling before completing "
                                "the response. Auto-bump retries exhausted."
                            ),
                            original_error=e,
                        )
                        continue

                    raise ProviderError(
                        provider=self.name,
                        message=(
                            "Model hit the output token ceiling before completing the "
                            "response. Reduce input complexity or use a model with a "
                            "higher output ceiling (gpt-4.1: 32 768 output tokens, "
                            "gpt-4o: 16 384). On a reasoning model, reasoning tokens "
                            "count against the budget; try a lower reasoning effort."
                        ),
                        original_error=e,
                    )

            # Exhausted all retries
            if last_length_error:
                raise last_length_error
            raise ProviderError(  # pragma: no cover — defensive
                provider=self.name,
                message="Auto-bump retries exhausted without producing valid output",
            )

        except AuthenticationError as e:
            raise ProviderAuthError(
                provider=self.name,
                message="Authentication failed - check API key",
                original_error=e,
            )
        except RateLimitError as e:
            raise ProviderRateLimitError(
                provider=self.name,
                message="Rate limit exceeded",
                original_error=e,
            )
        except APIError as e:
            raise map_sdk_api_error(
                self.name,
                e,
                timeout_error=APITimeoutError,
                connection_error=APIConnectionError,
            ) from e

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate plain text output."""
        try:
            response = await self._call(
                self._client.chat.completions.create,
                budget=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            self._record_usage(getattr(response, "usage", None))

            return response.choices[0].message.content

        except AuthenticationError as e:
            raise ProviderAuthError(
                provider=self.name,
                message="Authentication failed - check API key",
                original_error=e,
            )
        except RateLimitError as e:
            raise ProviderRateLimitError(
                provider=self.name,
                message="Rate limit exceeded",
                original_error=e,
            )
        except APIError as e:
            raise map_sdk_api_error(
                self.name,
                e,
                timeout_error=APITimeoutError,
                connection_error=APIConnectionError,
            ) from e

    async def __aenter__(self) -> "OpenAIProvider":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager.

        The OpenAI sync SDK client doesn't require explicit resource cleanup,
        but this method is provided for protocol consistency.
        """
        pass  # OpenAI sync client doesn't need explicit closing
