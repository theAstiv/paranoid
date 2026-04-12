"""OpenAI LLM provider implementation."""

import json
from typing import TypeVar

from openai import APIError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    run_sync_in_executor,
    strip_markdown_fences,
)


T = TypeVar("T", bound=BaseModel)

# Module-level cache for model_json_schema() results — deterministic per class.
_schema_cache: dict[type, dict] = {}


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
        timeout: float = 60.0,
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

        Note: OpenAI JSON mode + vision is only supported on gpt-4o and gpt-4o-mini.
        Models like gpt-4-vision-preview do not support JSON mode with images.

        shared_context is prepended to the user prompt text. OpenAI does not support
        prompt caching via content blocks, so the benefit here is semantic consistency
        with the Anthropic path rather than a cost reduction.
        """
        try:
            # Get JSON schema from Pydantic model (cached per class — deterministic)
            if response_model not in _schema_cache:
                _schema_cache[response_model] = response_model.model_json_schema()
            schema = _schema_cache[response_model]

            # Use JSON mode with schema guidance (compact JSON, no indent)
            system_prompt = (
                f"You must respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema)}\n\n"
                f"Respond ONLY with the JSON object."
            )

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

            # Call OpenAI API with JSON mode (async)
            response = await run_sync_in_executor(
                self._client.chat.completions.create,
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )

            # Extract and clean JSON content (defensive fence stripping)
            content = response.choices[0].message.content
            content = strip_markdown_fences(content)

            # Parse and validate
            try:
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                raise ProviderError(
                    provider=self.name,
                    message=f"Failed to parse structured output: {e}",
                    original_error=e,
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
