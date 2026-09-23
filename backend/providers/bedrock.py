"""AWS Bedrock LLM provider implementation using the Converse API."""

import base64
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from backend.models.extended import ImageContent
from backend.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    run_sync_in_executor,
)


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MAX_AUTO_BUMP = 16384
_MAX_RETRIES = 2

# Module-level schema cache — deterministic per class, computed once.
_schema_cache: dict[type, dict] = {}

# Bedrock model IDs use dotted-path format: e.g.
#   us.anthropic.claude-sonnet-4-20250514-v1:0
#   amazon.nova-pro-v1:0
# Plain API format IDs (e.g. "claude-sonnet-4-20250514") do not contain a "."
# and are rejected with a clear error so the user gets actionable feedback.
_BEDROCK_ID_HINT = (
    "Bedrock model IDs use provider-namespaced format, e.g. "
    "'us.anthropic.claude-sonnet-4-20250514-v1:0' or 'amazon.nova-pro-v1:0'. "
    "Plain API model IDs (e.g. 'claude-sonnet-4-20250514') are not accepted."
)


class BedrockProvider:
    """AWS Bedrock provider using the Converse API for structured output.

    Supports Claude on Bedrock and Amazon Nova models. Models that do not
    support toolChoice (e.g. Llama, Mistral) are not supported — there is no
    JSON-mode fallback.

    Authentication follows the standard boto3 credential chain:
    environment variables → ~/.aws/credentials → IAM roles. No explicit
    access key parameters are accepted; use AWS_PROFILE or IAM roles instead.
    """

    def __init__(
        self,
        model: str,
        region: str = "us-east-1",
        profile: str = "",
    ):
        """Initialise Bedrock provider.

        Args:
            model: Bedrock model ID in provider-namespaced format.
            region: AWS region for the Bedrock endpoint.
            profile: AWS named profile (empty string = default credential chain).

        Raises:
            ImportError: If boto3 is not installed.
            ValueError: If model ID uses plain API format instead of Bedrock format.
        """
        try:
            import boto3
            import botocore.config
        except ImportError:
            raise ImportError(
                "boto3 is required for the Bedrock provider. "
                "Install with: pip install paranoid-cli[bedrock]"
            )

        if "." not in model:
            raise ValueError(f"Invalid Bedrock model ID {model!r}. {_BEDROCK_ID_HINT}")

        self._model = model
        self._region = region

        session = boto3.Session(profile_name=profile or None)
        self._client = session.client(
            "bedrock-runtime",
            region_name=region,
            config=botocore.config.Config(
                read_timeout=240,
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
        )

    @property
    def name(self) -> str:
        return "bedrock"

    @property
    def model(self) -> str:
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
        """Generate structured output via Bedrock Converse API with toolConfig.

        Auto-bumps max_tokens 2x on truncation, up to _MAX_AUTO_BUMP, max _MAX_RETRIES retries.
        """
        try:
            if response_model not in _schema_cache:
                _schema_cache[response_model] = response_model.model_json_schema()
            schema = _schema_cache[response_model]

            tool_config: dict[str, Any] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "respond",
                            "description": (
                                "Respond with structured JSON conforming to the provided schema."
                            ),
                            "inputSchema": {"json": schema},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": "respond"}},
            }

            content_blocks = _build_content_blocks(prompt, images, shared_context)
            budget = max_tokens or 4096
            last_error: ProviderError | None = None

            for attempt in range(1 + _MAX_RETRIES):
                response = await run_sync_in_executor(
                    self._client.converse,
                    modelId=self._model,
                    messages=[{"role": "user", "content": content_blocks}],
                    toolConfig=tool_config,
                    inferenceConfig={"maxTokens": budget, "temperature": temperature},
                )

                stop_reason = response.get("stopReason", "")

                if stop_reason == "max_tokens" and budget < _MAX_AUTO_BUMP:
                    old = budget
                    budget = min(budget * 2, _MAX_AUTO_BUMP)
                    logger.warning(
                        "Bedrock output truncated (max_tokens) at %d, bumping to %d (attempt %d/%d)",
                        old,
                        budget,
                        attempt + 1,
                        1 + _MAX_RETRIES,
                    )
                    continue

                # Extract tool_use response block
                output_content = response.get("output", {}).get("message", {}).get("content", [])
                tool_block = next(
                    (b for b in output_content if b.get("toolUse")),
                    None,
                )
                if tool_block is None:
                    raise ProviderError(
                        provider=self.name,
                        message=f"Bedrock returned no tool_use block (stopReason={stop_reason!r})",
                    )

                data = tool_block["toolUse"]["input"]
                try:
                    return response_model.model_validate(data)
                except ValidationError as e:
                    last_error = ProviderError(
                        provider=self.name,
                        message=f"Failed to validate structured output: {e}",
                        original_error=e,
                    )
                    if attempt < _MAX_RETRIES and budget < _MAX_AUTO_BUMP:
                        budget = min(budget * 2, _MAX_AUTO_BUMP)
                        continue
                    raise last_error

            if last_error:
                raise last_error
            raise ProviderError(  # pragma: no cover
                provider=self.name,
                message="Auto-bump retries exhausted without producing valid output",
            )

        except ProviderError:
            raise
        except Exception as e:
            raise _map_boto_error(self.name, e) from e

    async def generate(
        self,
        prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Generate plain text via Bedrock Converse API (no toolConfig)."""
        try:
            response = await run_sync_in_executor(
                self._client.converse,
                modelId=self._model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "maxTokens": max_tokens or 4096,
                    "temperature": temperature,
                },
            )
            output_content = response.get("output", {}).get("message", {}).get("content", [])
            text_block = next((b for b in output_content if "text" in b), None)
            if text_block is None:
                raise ProviderError(provider=self.name, message="Bedrock returned no text block")
            return text_block["text"]

        except ProviderError:
            raise
        except Exception as e:
            raise _map_boto_error(self.name, e) from e

    async def __aenter__(self) -> "BedrockProvider":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def _build_content_blocks(
    prompt: str,
    images: list[ImageContent] | None,
    shared_context: str | None,
) -> list[dict]:
    """Build Converse API content block list.

    Order: images → shared_context → prompt (same stable-prefix convention as Anthropic provider).
    """
    blocks: list[dict] = []

    if images:
        for img in images:
            # Decode base64 to bytes — Bedrock Converse expects raw bytes in image.source.bytes
            raw_bytes = base64.b64decode(img.data)
            fmt = img.media_type.split("/")[-1]  # "image/png" → "png"
            blocks.append({"image": {"format": fmt, "source": {"bytes": raw_bytes}}})

    if shared_context:
        blocks.append({"text": shared_context})

    blocks.append({"text": prompt})
    return blocks


def _map_boto_error(provider_name: str, exc: Exception) -> ProviderError:
    """Map botocore/boto3 exceptions to ProviderError subclasses."""
    try:
        import importlib

        bce = importlib.import_module("botocore.exceptions")

        if isinstance(exc, bce.NoCredentialsError):
            return ProviderAuthError(
                provider=provider_name,
                message="No AWS credentials found. Configure via environment, ~/.aws/credentials, or IAM role.",
                original_error=exc,
            )

        if isinstance(exc, bce.ClientError):
            code = exc.response["Error"]["Code"]
            if code == "AccessDeniedException":
                return ProviderAuthError(
                    provider=provider_name,
                    message=f"AWS access denied: {exc.response['Error'].get('Message', code)}",
                    original_error=exc,
                )
            if code == "ThrottlingException":
                return ProviderRateLimitError(
                    provider=provider_name,
                    message="Bedrock rate limit exceeded",
                    original_error=exc,
                )
            if code == "ModelTimeoutException":
                return ProviderTimeoutError(
                    provider=provider_name,
                    message="Bedrock model timed out",
                    original_error=exc,
                )
            return ProviderError(
                provider=provider_name,
                message=f"Bedrock error [{code}]: {exc.response['Error'].get('Message', '')}",
                original_error=exc,
            )

    except ImportError:
        pass

    return ProviderError(provider=provider_name, message=str(exc), original_error=exc)
