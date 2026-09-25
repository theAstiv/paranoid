"""Anthropic LLM provider implementation."""

import json
import logging
from typing import TypeVar

from anthropic import Anthropic, APIError, AuthenticationError, BadRequestError, RateLimitError
from pydantic import BaseModel, ValidationError

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    run_sync_in_executor,
    strip_markdown_fences,
)


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Auto-bump: when the model's output is truncated (stop_reason == "max_tokens"
# or the JSON fails to parse with a truncation-specific pattern), retry with
# 2x the token budget.  At most _MAX_RETRIES additional attempts; hard ceiling
# to avoid runaway costs.
_MAX_AUTO_BUMP = 16384
_MAX_RETRIES = 2
_TRUNCATION_PATTERNS = ("Extra data", "Unterminated string", "Expecting ',' delimiter")

# Module-level cache for model_json_schema() results — these are deterministic
# per class and can be computed once rather than on every API call.
_schema_cache: dict[type, dict] = {}


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
        # Some model families (e.g. claude-sonnet-5) reject `temperature`
        # outright with a 400 rather than accepting/ignoring it. Detected
        # lazily on first call and cached per instance so later calls for
        # the same model+process skip the doomed round-trip entirely.
        self._temperature_unsupported = False

    @staticmethod
    def _is_temperature_deprecated_error(e: BadRequestError) -> bool:
        message = str(e).lower()
        return "temperature" in message and (
            "deprecated" in message or "not supported" in message or "unsupported" in message
        )

    def _extract_text(self, response) -> str:
        """Return the first text block's content.

        Extended-thinking-capable models (e.g. claude-sonnet-5) put a
        `ThinkingBlock` at `content[0]` ahead of the actual `TextBlock` —
        indexing `content[0]` directly picks up the thinking trace instead
        of the response and fails with `AttributeError: no attribute 'text'`
        the moment thinking produces any content, so every text block is
        scanned for the first one that actually has `.text`.
        """
        for block in response.content:
            text = getattr(block, "text", None)
            if text is not None:
                return text
        raise ProviderError(
            provider=self.name,
            message=f"No text block in response.content (got: {[type(b).__name__ for b in response.content]})",
        )

    async def _create_message(self, temperature: float, **kwargs):
        """Call `messages.create`, retrying once without `temperature` if this
        model rejects it outright (some model families do, as a 400 rather
        than accepting/silently ignoring it)."""
        if not self._temperature_unsupported:
            try:
                return await run_sync_in_executor(
                    self._client.messages.create, temperature=temperature, **kwargs
                )
            except BadRequestError as e:
                if not self._is_temperature_deprecated_error(e):
                    raise
                self._temperature_unsupported = True
                logger.warning(
                    "Model %s rejects the `temperature` parameter — omitting it "
                    "for the rest of this provider instance's calls",
                    self._model,
                )
        return await run_sync_in_executor(self._client.messages.create, **kwargs)

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
        shared_context: str | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        Supports vision API for PNG/JPG images via content blocks.

        **Auto-bump:** When the model's output is truncated (``stop_reason``
        is ``max_tokens``, or the JSON fails to parse with a truncation
        pattern like "Extra data" / "Unterminated string"), the method
        automatically retries with 2x the token budget, up to
        ``_MAX_AUTO_BUMP`` and ``_MAX_RETRIES`` additional attempts.

        When shared_context is provided it is sent as a separate content block
        marked with cache_control: ephemeral so Anthropic's prompt cache can
        serve it from cache for every call in the same pipeline run (5-min TTL).
        The system prompt block is always marked cacheable; images are marked
        cacheable when shared_context is also present (they are stable too).
        """
        try:
            # Get JSON schema from Pydantic model (cached per class — deterministic)
            if response_model not in _schema_cache:
                _schema_cache[response_model] = response_model.model_json_schema()
            schema = _schema_cache[response_model]

            # Construct system prompt for JSON output (compact JSON, no indent).
            # Passed as a list of blocks so cache_control can be applied — Anthropic
            # caches the system block across calls that share the exact same content.
            schema_text = (
                f"You must respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema)}\n\n"
                f"Respond ONLY with the JSON object, no other text."
            )
            system = [{"type": "text", "text": schema_text, "cache_control": {"type": "ephemeral"}}]

            # Build user content blocks.
            # Order: images → shared_context (cacheable) → dynamic prompt (not cached).
            # Images and shared_context get cache_control when shared_context is present
            # so the entire stable prefix is served from cache on subsequent calls.
            content: list[dict] = []

            if images:
                for img in images:
                    block: dict = {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.media_type,
                            "data": img.data,
                        },
                    }
                    if shared_context:
                        block["cache_control"] = {"type": "ephemeral"}
                    content.append(block)

            if shared_context:
                content.append(
                    {
                        "type": "text",
                        "text": shared_context,
                        "cache_control": {"type": "ephemeral"},
                    }
                )

            content.append({"type": "text", "text": prompt})

            # ── Auto-bump retry loop ──────────────────────────────────────
            budget = max_tokens or 4096
            last_error: ProviderError | None = None

            for attempt in range(1 + _MAX_RETRIES):
                response = await self._create_message(
                    temperature,
                    model=self._model,
                    max_tokens=budget,
                    system=system,
                    messages=[{"role": "user", "content": content}],
                )

                # ── Check for explicit truncation ─────────────────────────
                if response.stop_reason == "max_tokens" and budget < _MAX_AUTO_BUMP:
                    old = budget
                    budget = min(budget * 2, _MAX_AUTO_BUMP)
                    logger.warning(
                        "Output truncated (stop_reason=max_tokens) at %d tokens, "
                        "auto-bumping to %d (attempt %d/%d)",
                        old,
                        budget,
                        attempt + 1,
                        1 + _MAX_RETRIES,
                    )
                    continue

                # ── Parse JSON ────────────────────────────────────────────
                response_text = self._extract_text(response)
                response_text = strip_markdown_fences(response_text)

                try:
                    # strict=False allows raw control characters (literal
                    # newlines, tabs, ...) inside JSON string values instead
                    # of raising "Invalid control character" — claude-sonnet-5
                    # emits these in longer free-text fields (e.g. gap_analysis)
                    # without escaping them, even though the content itself is
                    # otherwise valid.
                    data = json.loads(response_text, strict=False)
                    return response_model.model_validate(data)
                except json.JSONDecodeError as e:
                    err_str = str(e)

                    # "Extra data" means valid JSON followed by trailing prose.
                    # Try parsing just the valid prefix before bumping or failing.
                    if "Extra data" in err_str:
                        try:
                            data = json.loads(response_text[: e.pos], strict=False)
                            return response_model.model_validate(data)
                        except (json.JSONDecodeError, ValidationError):
                            pass

                    is_truncation = any(pat in err_str for pat in _TRUNCATION_PATTERNS)

                    if is_truncation and attempt < _MAX_RETRIES and budget < _MAX_AUTO_BUMP:
                        old = budget
                        budget = min(budget * 2, _MAX_AUTO_BUMP)
                        logger.warning(
                            "Output likely truncated (%s) at %d tokens, "
                            "auto-bumping to %d (attempt %d/%d)",
                            err_str[:80],
                            old,
                            budget,
                            attempt + 1,
                            1 + _MAX_RETRIES,
                        )
                        last_error = ProviderError(
                            provider=self.name,
                            message=f"Failed to parse structured output: {e}",
                            original_error=e,
                        )
                        continue

                    raise ProviderError(
                        provider=self.name,
                        message=f"Failed to parse structured output: {e}",
                        original_error=e,
                    )
                except ValidationError as e:
                    raise ProviderError(
                        provider=self.name,
                        message=f"Failed to parse structured output: {e}",
                        original_error=e,
                    )

            # Exhausted all retries — raise the last error
            if last_error:
                raise last_error
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
            # Call Anthropic API in thread pool (sync SDK)
            response = await self._create_message(
                temperature,
                model=self._model,
                max_tokens=max_tokens or 4096,
                messages=[{"role": "user", "content": prompt}],
            )

            return self._extract_text(response)

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
