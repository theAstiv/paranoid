"""Ollama LLM provider implementation for local/self-hosted models."""

import json
import logging
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderError,
    ProviderTimeoutError,
    strip_markdown_fences,
)


logger = logging.getLogger(__name__)


T = TypeVar("T", bound=BaseModel)


class OllamaProvider:
    """Ollama provider for local/self-hosted models.

    Usage as async context manager (recommended):
        async with OllamaProvider(model="llama3") as provider:
            result = await provider.generate_structured(...)

    This ensures the HTTP client is properly closed.
    """

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        timeout: float = 120.0,
    ):
        """Initialize Ollama provider.

        Args:
            model: Model identifier (e.g., 'llama3', 'mistral')
            base_url: Ollama server URL (default: http://localhost:11434)
            timeout: Request timeout in seconds (local models can be slower)
        """
        self._model = model
        self._base_url = base_url or "http://localhost:11434"
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def name(self) -> str:
        """Provider name."""
        return "ollama"

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

        Note: Ollama does not support vision for most models. Images are ignored
        with a warning. Consider using Anthropic or OpenAI for vision-based threat modeling.
        """
        # Graceful degradation: log warning if images provided
        if images:
            logger.warning(
                f"Ollama provider (model: {self._model}) does not support vision. "
                f"Architecture diagram will be ignored. Consider using Anthropic or OpenAI providers."
            )

        try:
            # Get JSON schema from Pydantic model
            schema = response_model.model_json_schema()

            # Construct prompt with JSON schema guidance
            enhanced_prompt = (
                f"{prompt}\n\n"
                f"Respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema, indent=2)}\n\n"
                f"Output ONLY the JSON object, no additional text."
            )

            # Call Ollama API
            response = await self._client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": enhanced_prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                    "format": "json",  # Request JSON output
                },
            )

            response.raise_for_status()
            result = response.json()
            content = result.get("response", "")

            # Clean content (defensive fence stripping)
            content = strip_markdown_fences(content)

            # Parse and validate JSON
            try:
                data = json.loads(content)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as e:
                raise ProviderError(
                    provider=self.name,
                    message=f"Failed to parse structured output: {e}",
                    original_error=e,
                )

        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                provider=self.name,
                message=f"Request timed out after {self._timeout}s",
                original_error=e,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                provider=self.name,
                message=f"HTTP {e.response.status_code}: {e.response.text}",
                original_error=e,
            )
        except httpx.RequestError as e:
            raise ProviderError(
                provider=self.name,
                message=f"Connection error - is Ollama running at {self._base_url}?",
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
            response = await self._client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
            )

            response.raise_for_status()
            result = response.json()
            return result.get("response", "")

        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(
                provider=self.name,
                message=f"Request timed out after {self._timeout}s",
                original_error=e,
            )
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                provider=self.name,
                message=f"HTTP {e.response.status_code}: {e.response.text}",
                original_error=e,
            )
        except httpx.RequestError as e:
            raise ProviderError(
                provider=self.name,
                message=f"Connection error - is Ollama running at {self._base_url}?",
                original_error=e,
            )

    async def __aenter__(self) -> "OllamaProvider":
        """Enter async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and close HTTP client."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        await self._client.aclose()
