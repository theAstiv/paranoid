"""OpenAI LLM provider implementation."""

import logging
from typing import TypeVar

from openai import APIError, AuthenticationError, LengthFinishReasonError, OpenAI, RateLimitError
from pydantic import BaseModel

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    run_sync_in_executor,
)


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Auto-bump constants — mirror the Anthropic provider.
# OpenAI's hard ceilings differ by model (gpt-4o: 16 384, gpt-4.1: 32 768),
# but our retry logic just doubles the *requested* budget; the model will still
# cap at its own maximum.
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
    ):
        """Initialize OpenAI provider.

        Args:
            model: Model identifier (e.g., 'gpt-4', 'gpt-4-turbo')
            api_key: OpenAI API key
            base_url: Custom API base URL (for Azure or compatible APIs)
            max_retries: Number of retry attempts for failed requests
            timeout: Request timeout in seconds
        """
        self._model = model
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        """Provider name."""
        return "openai"

    @property
    def model(self) -> str:
        """Model identifier."""
        return self._model

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

            # Add images as data URIs
            if images:
                for img in images:
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
                    response = await run_sync_in_executor(
                        self._client.chat.completions.parse,
                        model=self._model,
                        max_tokens=budget,
                        temperature=temperature,
                        response_format=response_model,
                        messages=[
                            {"role": "user", "content": user_content},
                        ],
                    )

                    parsed = response.choices[0].message.parsed
                    if parsed is None:
                        refusal = response.choices[0].message.refusal
                        raise ProviderError(
                            provider=self.name,
                            message=f"Model returned no parsed output (refusal: {refusal})",
                        )
                    return parsed

                except LengthFinishReasonError as e:
                    # Model hit its output token ceiling before completing JSON.
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
                            "higher output ceiling (gpt-4.1 supports 32 768 output "
                            "tokens vs gpt-4o's 16 384)."
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
            raise ProviderError(
                provider=self.name,
                message=f"API error: {e!s}",
                original_error=e,
            )

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate plain text output."""
        try:
            response = await run_sync_in_executor(
                self._client.chat.completions.create,
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )

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
            raise ProviderError(
                provider=self.name,
                message=f"API error: {e!s}",
                original_error=e,
            )

    async def __aenter__(self) -> "OpenAIProvider":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager.

        The OpenAI sync SDK client doesn't require explicit resource cleanup,
        but this method is provided for protocol consistency.
        """
        pass  # OpenAI sync client doesn't need explicit closing
