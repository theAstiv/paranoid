"""Which provider and model the live suites run on.

Defaults to the direct Anthropic API with `DEFAULT_MODEL` from the repo's `.env`,
the behaviour these suites always had. To run them on another provider (e.g. AWS
Bedrock for the bug bash), set in the environment or `tests/bench/bench.env`:

    BENCH_LIVE_MODEL=SONNET_55          # a bench slot name: provider + model ID from bench.env
    BENCH_LIVE_PROVIDER=bedrock         # ...or a provider plus a raw model ID
    BENCH_LIVE_MODEL=us.anthropic.claude-sonnet-5-5

Precedence: real environment > `tests/bench/bench.env` > the repo's `.env`.
"""

from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

from backend.providers import create_provider
from backend.providers.base import LLMProvider
from backend.routes._helpers import bedrock_kwargs, effort_kwargs
from tests.bench.config import SLOTS, merged_env, resolve_slot


_ROOT = Path(__file__).resolve().parent.parent.parent
_PROVIDERS = {"anthropic", "bedrock", "openai", "ollama"}


def _load_env() -> dict[str, str]:
    repo_env = {k: v for k, v in dotenv_values(_ROOT / ".env").items() if v is not None}
    return {**repo_env, **merged_env()}


def resolve_live_target(env: dict[str, str]) -> tuple[str, str]:
    """Return (provider, model) for the live suites. Raises ValueError on a typo,
    so a misspelt provider fails collection instead of silently skipping."""
    model = env.get("BENCH_LIVE_MODEL", "").strip()
    if model in SLOTS:
        resolved = resolve_slot(model, env)
        if resolved is None:
            # The slot exists but its model ID isn't configured; skip_reason() says so.
            return SLOTS[model].provider, ""
        return resolved.provider, resolved.model_id

    provider = env.get("BENCH_LIVE_PROVIDER", "").strip().lower() or "anthropic"
    if provider not in _PROVIDERS:
        raise ValueError(f"BENCH_LIVE_PROVIDER={provider!r} is not one of {sorted(_PROVIDERS)}")
    if not model and provider == "anthropic":
        model = env.get("DEFAULT_MODEL", "").strip()
    return provider, model


def _bedrock_skip_reason(env: dict[str, str]) -> str | None:
    try:
        import boto3
    except ImportError:
        return "bedrock needs boto3: pip install -e '.[bedrock]'"
    session = boto3.Session(profile_name=env.get("AWS_PROFILE") or None)
    if session.get_credentials() is None:
        return "bedrock needs AWS credentials (AWS_PROFILE or the default chain)"
    if not (env.get("AWS_REGION") or session.region_name):
        return "bedrock needs AWS_REGION"
    return None


def skip_reason(provider: str, model: str, env: dict[str, str]) -> str | None:
    """Why the live suites can't run on this provider here, or None if they can."""
    if not model:
        return f"no model for {provider}: set BENCH_LIVE_MODEL (or DEFAULT_MODEL for anthropic)"
    if provider == "anthropic":
        key = env.get("ANTHROPIC_API_KEY", "")
        if not key or key.startswith("sk-ant-xxx"):
            return "needs a real ANTHROPIC_API_KEY (set in .env or the environment)"
    elif provider == "openai" and not env.get("OPENAI_API_KEY", "").strip():
        return "needs OPENAI_API_KEY"
    elif provider == "bedrock":
        return _bedrock_skip_reason(env)
    return None


def build_live_provider(
    provider: str, model: str, env: dict[str, str], *, timeout: float, max_retries: int
) -> LLMProvider:
    """The main provider for a live run, configured the way the web routes configure it."""
    effort = env.get("ANTHROPIC_EFFORT", "").strip() or env.get("BENCH_EFFORT", "").strip()
    cfg = SimpleNamespace(
        aws_region=env.get("AWS_REGION", ""),
        aws_profile=env.get("AWS_PROFILE", ""),
        bedrock_image_models=[
            m.strip() for m in env.get("BEDROCK_IMAGE_MODELS", "").split(",") if m.strip()
        ],
        anthropic_effort=effort or None,
    )
    # The providers' constructors differ: Bedrock takes neither timeout nor
    # max_retries (botocore owns both), and Ollama takes no max_retries.
    kwargs: dict = {**bedrock_kwargs(provider, cfg), **effort_kwargs(provider, model, cfg)}
    if provider in ("anthropic", "openai"):
        kwargs.update(timeout=timeout, max_retries=max_retries)
    elif provider == "ollama":
        kwargs.update(timeout=timeout)
    api_key = {
        "anthropic": env.get("ANTHROPIC_API_KEY"),
        "openai": env.get("OPENAI_API_KEY"),
    }.get(provider)
    base_url = (env.get("OLLAMA_BASE_URL") or None) if provider == "ollama" else None
    return create_provider(
        provider_type=provider, model=model, api_key=api_key, base_url=base_url, **kwargs
    )


LIVE_ENV = _load_env()
LIVE_PROVIDER, LIVE_MODEL = resolve_live_target(LIVE_ENV)
LIVE_SKIP_REASON = skip_reason(LIVE_PROVIDER, LIVE_MODEL, LIVE_ENV)
LIVE_LABEL = f"{LIVE_PROVIDER}:{LIVE_MODEL or '?'}"
