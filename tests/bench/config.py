"""Environment-driven configuration: model slots, harness settings, the env file loader."""

import os
from pathlib import Path

from dotenv import dotenv_values
from pydantic import BaseModel


BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parent.parent
DEFAULT_ENV_FILE = BENCH_DIR / "bench.env"


class ModelSlot(BaseModel):
    """A named place in the model matrix. The concrete model ID comes from `env_var`."""

    name: str
    provider: str  # "bedrock" | "openai"
    env_var: str
    family: str  # "claude" | "openai" | "open-weight"
    images_by_default: bool
    default_id: str | None = None


class ResolvedModel(BaseModel):
    slot: str
    provider: str
    model_id: str
    family: str
    images: bool


# Image defaults are conservative until the spike (SB2) and P-2 settle them per model:
# Claude on Bedrock takes images; gpt-oss, Qwen and DeepSeek are treated as text-only.
SLOTS: dict[str, ModelSlot] = {
    s.name: s
    for s in [
        ModelSlot(
            name="OPUS_55",
            provider="bedrock",
            env_var="BENCH_MODEL_OPUS_55",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="FABLE_51",
            provider="bedrock",
            env_var="BENCH_MODEL_FABLE_51",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="SONNET_55",
            provider="bedrock",
            env_var="BENCH_MODEL_SONNET_55",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="SONNET_5",
            provider="bedrock",
            env_var="BENCH_MODEL_SONNET_5",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="HAIKU_55",
            provider="bedrock",
            env_var="BENCH_MODEL_HAIKU_55",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="HAIKU_45",
            provider="bedrock",
            env_var="BENCH_MODEL_HAIKU_45",
            family="claude",
            images_by_default=True,
        ),
        ModelSlot(
            name="GPT_OSS_120B",
            provider="bedrock",
            env_var="BENCH_MODEL_GPT_OSS_120B",
            family="openai",
            images_by_default=False,
        ),
        ModelSlot(
            name="GPT_OSS_20B",
            provider="bedrock",
            env_var="BENCH_MODEL_GPT_OSS_20B",
            family="openai",
            images_by_default=False,
        ),
        ModelSlot(
            name="QWEN",
            provider="bedrock",
            env_var="BENCH_MODEL_QWEN",
            family="open-weight",
            images_by_default=False,
        ),
        ModelSlot(
            name="DEEPSEEK",
            provider="bedrock",
            env_var="BENCH_MODEL_DEEPSEEK",
            family="open-weight",
            images_by_default=False,
        ),
        ModelSlot(
            name="OPENAI_DIRECT",
            provider="openai",
            env_var="BENCH_MODEL_OPENAI_DIRECT",
            family="openai",
            images_by_default=True,
            default_id="gpt-4.1",
        ),
    ]
}

# The settings a run may forward to the pipeline subprocess. Everything else in the
# parent environment passes through untouched but is never written to an artifact.
ARTIFACT_SAFE_KEYS = (
    "AWS_REGION",
    "AWS_PROFILE",
    "ANTHROPIC_EFFORT",
    "BENCH_EFFORT",
    "DEFAULT_PROVIDER",
    "FAST_MODEL",
    "FAST_MODEL_BEDROCK",
    "FAST_MODEL_OPENAI",
    "MIN_ITERATIONS",
    "DEPS_ANALYSIS_TIMEOUT_SECONDS",
)


def load_env_file(path: Path | None = None) -> dict[str, str]:
    """Return the bench env file's values without touching os.environ.

    Real environment variables win over the file, so a one-off override on the
    command line never needs an edit to bench.env.
    """
    env_path = path or Path(os.environ.get("BENCH_ENV_FILE", DEFAULT_ENV_FILE))
    if not env_path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(env_path).items() if v is not None}


def merged_env(path: Path | None = None) -> dict[str, str]:
    """File values overlaid by the real environment."""
    return {**load_env_file(path), **os.environ}


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _has_openai_key(env: dict[str, str]) -> bool:
    if env.get("OPENAI_API_KEY", "").strip():
        return True
    # The backend also reads the repo's .env; only presence is checked, the value never leaves this function.
    repo_env = REPO_ROOT / ".env"
    return repo_env.is_file() and bool(
        (dotenv_values(repo_env).get("OPENAI_API_KEY") or "").strip()
    )


def resolve_slot(name: str, env: dict[str, str]) -> ResolvedModel | None:
    """The concrete model for a slot, or None when it can't run (slot skipped).

    A Bedrock slot needs its model ID; the direct OpenAI slot also needs an API key.
    """
    slot = SLOTS[name]
    model_id = env.get(slot.env_var, "").strip() or (slot.default_id or "")
    if not model_id:
        return None
    if slot.provider == "openai" and not _has_openai_key(env):
        return None
    images_override = env.get(f"BENCH_IMAGES_{name}", "").strip()
    images = _truthy(images_override) if images_override else slot.images_by_default
    return ResolvedModel(
        slot=name, provider=slot.provider, model_id=model_id, family=slot.family, images=images
    )


class BenchSettings(BaseModel):
    out_dir: Path
    prices_file: Path | None
    max_cost_usd: float | None
    effort: str
    run_timeout_s: int
    routing_main: str | None
    routing_fast: str | None
    code_repo: Path | None
    malware_dir: Path | None


def load_settings(env: dict[str, str]) -> BenchSettings:
    def _path(key: str) -> Path | None:
        value = env.get(key, "").strip()
        return Path(value) if value else None

    max_cost = env.get("BENCH_MAX_COST_USD", "").strip()
    return BenchSettings(
        out_dir=_path("BENCH_OUT_DIR") or REPO_ROOT / "data" / "benchmarks",
        prices_file=_path("BENCH_PRICES_FILE"),
        max_cost_usd=float(max_cost) if max_cost else None,
        effort=env.get("BENCH_EFFORT", "").strip() or "medium",
        run_timeout_s=int(env.get("BENCH_RUN_TIMEOUT_S", "").strip() or 1800),
        routing_main=env.get("BENCH_ROUTING_MAIN", "").strip() or None,
        routing_fast=env.get("BENCH_ROUTING_FAST", "").strip() or None,
        code_repo=_path("BENCH_CODE_REPO"),
        malware_dir=_path("BENCH_MALWARE_DIR"),
    )
