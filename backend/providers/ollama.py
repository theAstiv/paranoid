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

# Auto-bump constants — Ollama truncation is detected via done_reason="length"
# or JSON parse errors with truncation patterns.
_MAX_AUTO_BUMP = 32768
_MAX_RETRIES = 2
_TRUNCATION_PATTERNS = ("Extra data", "Unterminated string", "Expecting ',' delimiter")

# Module-level cache for model_json_schema() results — deterministic per class.
_schema_cache: dict[type, dict] = {}


def _fill_missing_required(
    data: object,
    response_model: type[BaseModel],
    err: ValidationError,
) -> dict | None:
    """Patch a dict with default values for required fields the LLM omitted.

    Returns the patched dict, or None when the input wasn't a dict at the top
    level (in which case there's nothing we can repair). Defaults are chosen
    to be safe placeholders that satisfy Pydantic without lying about content:
    empty list / dict for container types, empty string for scalars.

    The repair is best-effort. If it produces a still-invalid structure the
    caller raises ProviderError with the original validation error.
    """
    if not isinstance(data, dict):
        return None

    # err.errors() reports each missing field as a tuple of (loc=(...path...), type="missing").
    patched: dict = json.loads(json.dumps(data))  # deep copy via JSON round-trip
    schema = response_model.model_json_schema()
    field_props = schema.get("properties", {})

    for issue in err.errors():
        if issue.get("type") != "missing":
            continue
        loc = issue.get("loc") or ()
        if not loc:
            continue
        field_name = loc[0]
        prop_schema = field_props.get(field_name, {})
        # Resolve the JSON-schema type; arrays/objects get empty containers,
        # everything else gets an empty string. This is intentionally coarse —
        # the goal is "let the pipeline produce a partial result" rather than
        # "guess the right value for a missing required field".
        json_type = prop_schema.get("type")
        if json_type == "array":
            patched.setdefault(field_name, [])
        elif json_type == "object":
            patched.setdefault(field_name, {})
        elif json_type in ("integer", "number"):
            patched.setdefault(field_name, 0)
        elif json_type == "boolean":
            patched.setdefault(field_name, False)
        else:
            patched.setdefault(field_name, "")

    return patched


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
        timeout: float = 300.0,
    ):
        """Initialize Ollama provider.

        Args:
            model: Model identifier (e.g., 'llama3.1:8b', 'mistral-nemo')
            base_url: Ollama server URL (default: http://localhost:11434)
            timeout: Request timeout in seconds. Default raised from 120s to 300s
                because dense MAESTRO extraction with num_predict=32768 can take
                3-5 minutes on a mid-range GPU; the previous ceiling triggered
                spurious timeouts on legitimate completions.
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
        shared_context: str | None = None,
    ) -> T:
        """Generate structured output conforming to a Pydantic model.

        **Auto-bump:** When Ollama truncates output (``done_reason`` is
        ``"length"``), or the JSON fails to parse with a truncation pattern,
        the method retries with 2x the ``num_predict`` budget up to
        ``_MAX_AUTO_BUMP`` / ``_MAX_RETRIES``.

        Note: Ollama does not support vision for most models. Images are ignored
        with a warning. Consider using Anthropic or OpenAI for vision-based threat modeling.

        shared_context is prepended to the prompt text. Ollama has no native caching
        mechanism, so this is semantically equivalent to a combined prompt.
        """
        # Graceful degradation: log warning if images provided
        if images:
            logger.warning(
                f"Ollama provider (model: {self._model}) does not support vision. "
                f"Architecture diagram will be ignored. Consider using Anthropic or OpenAI providers."
            )

        try:
            # Get JSON schema from Pydantic model (cached per class — deterministic)
            if response_model not in _schema_cache:
                _schema_cache[response_model] = response_model.model_json_schema()
            schema = _schema_cache[response_model]

            # Prepend shared_context to prompt text (no native caching on Ollama)
            full_prompt = f"{shared_context}\n\n{prompt}" if shared_context else prompt

            # Construct prompt with JSON schema guidance (compact JSON, no indent)
            enhanced_prompt = (
                f"{full_prompt}\n\n"
                f"Respond with valid JSON matching this schema:\n"
                f"{json.dumps(schema)}\n\n"
                f"Output ONLY the JSON object, no additional text."
            )

            # ── Auto-bump retry loop ──────────────────────────────────────
            budget = max_tokens or 4096
            last_error: ProviderError | None = None

            for attempt in range(1 + _MAX_RETRIES):
                response = await self._client.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "prompt": enhanced_prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": budget,
                        },
                        "format": "json",
                    },
                )

                response.raise_for_status()
                api_result = response.json()
                content = api_result.get("response", "")

                # ── Check for explicit truncation via done_reason ─────────
                done_reason = api_result.get("done_reason", "")
                if done_reason == "length" and budget < _MAX_AUTO_BUMP:
                    old = budget
                    budget = min(budget * 2, _MAX_AUTO_BUMP)
                    logger.warning(
                        "Ollama output truncated (done_reason=length) at "
                        "num_predict=%d, auto-bumping to %d (attempt %d/%d)",
                        old,
                        budget,
                        attempt + 1,
                        1 + _MAX_RETRIES,
                    )
                    continue

                # Clean content (defensive fence stripping)
                content = strip_markdown_fences(content)

                # Parse and validate JSON. Smaller Ollama-hosted models occasionally
                # drop required fields even with format=json — try a single repair
                # pass before giving up.
                try:
                    data = json.loads(content)
                except json.JSONDecodeError as e:
                    err_str = str(e)
                    is_truncation = any(pat in err_str for pat in _TRUNCATION_PATTERNS)

                    if is_truncation and attempt < _MAX_RETRIES and budget < _MAX_AUTO_BUMP:
                        old = budget
                        budget = min(budget * 2, _MAX_AUTO_BUMP)
                        logger.warning(
                            "Ollama output likely truncated (%s) at num_predict=%d, "
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

                try:
                    return response_model.model_validate(data)
                except ValidationError as initial_err:
                    repaired = _fill_missing_required(data, response_model, initial_err)
                    if repaired is None:
                        raise ProviderError(
                            provider=self.name,
                            message=f"Failed to parse structured output: {initial_err}",
                            original_error=initial_err,
                        )
                    try:
                        validated = response_model.model_validate(repaired)
                        logger.warning(
                            "Ollama (model: %s) response was missing required fields; "
                            "auto-filled with defaults to keep the pipeline running.",
                            self._model,
                        )
                        return validated
                    except ValidationError as e:
                        raise ProviderError(
                            provider=self.name,
                            message=f"Failed to parse structured output: {e}",
                            original_error=e,
                        )

            # Exhausted all retries
            if last_error:
                raise last_error
            raise ProviderError(  # pragma: no cover — defensive
                provider=self.name,
                message="Auto-bump retries exhausted without producing valid output",
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
