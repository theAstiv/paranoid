"""Base protocol for LLM providers."""

import asyncio
import functools
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from backend.models.extended import ImageContent


T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Protocol for LLM providers supporting structured output.

    Providers should be used as async context managers to ensure proper
    resource cleanup:

        async with provider:
            result = await provider.generate_structured(...)
    """

    async def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        images: list[ImageContent] | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        Args:
            prompt: The prompt text to send to the model
            response_model: Pydantic model class for structured output
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response (None = provider default)
            images: Optional list of images for vision-enabled models (Claude/GPT-4 vision)

        Returns:
            Instance of response_model with LLM-generated data

        Raises:
            ProviderError: If the LLM request fails
            ValidationError: If LLM output doesn't match response_model
        """
        ...

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate plain text output.

        Args:
            prompt: The prompt text to send to the model
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response (None = provider default)

        Returns:
            Plain text response from the model

        Raises:
            ProviderError: If the LLM request fails
        """
        ...

    async def __aenter__(self) -> "LLMProvider":
        """Enter async context manager.

        Returns:
            Self for use in async with statement
        """
        ...

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and clean up resources.

        Ensures all connections and resources are properly closed.
        """
        ...

    @property
    def name(self) -> str:
        """Provider name (e.g., 'anthropic', 'openai', 'ollama')."""
        ...

    @property
    def model(self) -> str:
        """Model identifier being used."""
        ...


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(self, provider: str, message: str, original_error: Exception | None = None):
        self.provider = provider
        self.message = message
        self.original_error = original_error
        super().__init__(f"{provider}: {message}")


class ProviderTimeoutError(ProviderError):
    """Raised when provider request times out."""

    pass


class ProviderRateLimitError(ProviderError):
    """Raised when provider rate limit is exceeded."""

    pass


class ProviderAuthError(ProviderError):
    """Raised when provider authentication fails."""

    pass


# Utility functions for all providers


def strip_markdown_fences(content: str) -> str:
    """Strip markdown code fences from JSON output.

    Many LLMs wrap JSON in markdown code fences like:
    ```json
    {"key": "value"}
    ```

    This function strips those fences to get clean JSON.

    Args:
        content: Raw text content from LLM (may have fences)

    Returns:
        Clean content with fences removed
    """
    content = content.strip()

    # Remove opening fence
    if content.startswith("```json"):
        content = content[7:]  # Remove ```json
    elif content.startswith("```"):
        content = content[3:]  # Remove ```

    # Remove closing fence
    if content.endswith("```"):
        content = content[:-3]

    return content.strip()


async def run_sync_in_executor(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous function in a thread pool executor.

    This allows sync SDK calls to be used in async functions without
    blocking the event loop.

    Args:
        func: Synchronous function to run
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result from func

    Example:
        result = await run_sync_in_executor(
            client.messages.create,
            model="claude-sonnet-4-20250514",
            messages=[...],
        )

    Notes:
        - Uses get_running_loop() (Python 3.12+) instead of deprecated get_event_loop()
        - Uses functools.partial for clean args/kwargs handling
        - Currently uses default ThreadPoolExecutor (None). For production API server,
          consider creating a named executor with explicit pool size to avoid exhaustion
          under high concurrent load.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,  # TODO: Use named executor with explicit pool size for API server phase
        functools.partial(func, *args, **kwargs)
    )


def create_provider(
    provider_type: str,
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> LLMProvider:
    """Factory function to create LLM providers.

    Args:
        provider_type: Provider name ('anthropic', 'openai', 'ollama')
        model: Model identifier
        api_key: API key (required for anthropic/openai)
        base_url: Custom base URL (optional, used for ollama)
        **kwargs: Additional provider-specific configuration

    Returns:
        LLMProvider instance

    Raises:
        ValueError: If provider_type is not supported
    """
    if provider_type == "anthropic":
        from backend.providers.anthropic import AnthropicProvider

        if not api_key:
            raise ValueError("api_key required for Anthropic provider")
        return AnthropicProvider(model=model, api_key=api_key, **kwargs)

    if provider_type == "openai":
        from backend.providers.openai import OpenAIProvider

        if not api_key:
            raise ValueError("api_key required for OpenAI provider")
        return OpenAIProvider(model=model, api_key=api_key, base_url=base_url, **kwargs)

    if provider_type == "ollama":
        from backend.providers.ollama import OllamaProvider

        return OllamaProvider(model=model, base_url=base_url, **kwargs)

    raise ValueError(
        f"Unsupported provider: {provider_type}. "
        f"Supported: anthropic, openai, ollama"
    )
