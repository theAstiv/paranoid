"""Base protocol for LLM providers."""

from typing import Any, Protocol, Type, TypeVar

from pydantic import BaseModel


T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Protocol for LLM providers supporting structured output."""

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        Args:
            prompt: The prompt text to send to the model
            response_model: Pydantic model class for structured output
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response (None = provider default)

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

    elif provider_type == "openai":
        from backend.providers.openai import OpenAIProvider

        if not api_key:
            raise ValueError("api_key required for OpenAI provider")
        return OpenAIProvider(model=model, api_key=api_key, base_url=base_url, **kwargs)

    elif provider_type == "ollama":
        from backend.providers.ollama import OllamaProvider

        return OllamaProvider(model=model, base_url=base_url, **kwargs)

    else:
        raise ValueError(
            f"Unsupported provider: {provider_type}. "
            f"Supported: anthropic, openai, ollama"
        )
