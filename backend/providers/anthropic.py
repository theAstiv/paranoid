"""Anthropic LLM provider implementation."""

import json
from typing import Type, TypeVar

from anthropic import Anthropic, APIError, RateLimitError, AuthenticationError
from pydantic import BaseModel, ValidationError

from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
)


T = TypeVar("T", bound=BaseModel)


class AnthropicProvider:
    """Anthropic Claude provider with structured output support."""

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
        response_model: Type[T],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model."""
        try:
            # Get JSON schema from Pydantic model
            schema = response_model.model_json_schema()

            # Construct system prompt for JSON output
            system_prompt = (
                f"You must respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, indent=2)}\n\n"
                f"Respond ONLY with the JSON object, no other text."
            )

            # Call Anthropic API
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens or 4096,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text content
            content = response.content[0].text

            # Parse JSON and validate against Pydantic model
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
                message=f"API error: {str(e)}",
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
            response = self._client.messages.create(
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
                message=f"API error: {str(e)}",
                original_error=e,
            )
