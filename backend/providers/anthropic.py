"""Anthropic LLM provider implementation."""

import json
from typing import TypeVar

from anthropic import Anthropic, APIError, AuthenticationError, RateLimitError
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


class AnthropicProvider:
    """Anthropic Claude provider with structured output support.

    Usage as async context manager (recommended):
        async with AnthropicProvider(model="claude-sonnet-4", api_key="...") as provider:
            result = await provider.generate_structured(...)

    The Anthropic sync SDK client doesn't require explicit closing, but the
    context manager interface is provided for consistency with the Protocol.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        """Initialize Anthropic provider.

        Args:
            model: Model identifier (e.g., 'claude-sonnet-4')
            api_key: Anthropic API key
            max_retries: Number of retry attempts for failed requests
            timeout: Request timeout in seconds
        """
        self._model = model
        self._client = Anthropic(
            api_key=api_key,
            max_retries=max_retries,
            timeout=timeout,
        )

    @property
    def name(self) -> str:
        """Provider name."""
        return "anthropic"

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
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        Supports vision API for PNG/JPG images via content blocks.
        """
        try:
            # Get JSON schema from Pydantic model
            schema = response_model.model_json_schema()

            # Construct system prompt for JSON output
            system_prompt = (
                f"You must respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, indent=2)}\n\n"
                f"Respond ONLY with the JSON object, no other text."
            )

            # Build message content (images + text)
            content = []

            # Add images first (recommended by Anthropic docs)
            if images:
                for img in images:
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.media_type,
                            "data": img.data,
                        }
                    })

            # Add text prompt
            content.append({
                "type": "text",
                "text": prompt,
            })

            # Call Anthropic API in thread pool (sync SDK)
            response = await run_sync_in_executor(
                self._client.messages.create,
                model=self._model,
                max_tokens=max_tokens or 4096,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )

            # Extract and clean text content
            response_text = response.content[0].text
            response_text = strip_markdown_fences(response_text)

            # Parse JSON and validate against Pydantic model
            try:
                data = json.loads(response_text)
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
            # Call Anthropic API in thread pool (sync SDK)
            response = await run_sync_in_executor(
                self._client.messages.create,
                model=self._model,
                max_tokens=max_tokens or 4096,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            return response.content[0].text

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

    async def __aenter__(self) -> "AnthropicProvider":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager.

        The Anthropic sync SDK client doesn't require explicit resource cleanup,
        but this method is provided for protocol consistency.
        """
        pass  # Anthropic sync client doesn't need explicit closing
