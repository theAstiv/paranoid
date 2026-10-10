"""Application configuration using pydantic-settings."""

import json
import sys
from typing import Annotated, Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# Mirrors the keys of backend.pipeline.runner's _DEFAULT_STEP_MODELS — the
# subset of PipelineStep that actually calls an LLM and so can be routed —
# duplicated as plain strings rather than imported: that module does `from
# backend.config import settings` at its own module-load time, so importing
# it back from here would be circular at Settings() construction. A step
# like rule_engine/iterate/complete/analyze_dependencies never reaches a
# provider, so a STEP_MODELS entry for one would silently do nothing; kept
# out of this set so it's rejected instead. Keep in sync —
# tests/test_config_settings.py asserts the two match.
_VALID_PIPELINE_STEPS = {
    "summarize",
    "summarize_code",
    "extract_assets",
    "extract_flows",
    "generate_threats",
    "gap_analysis",
    "generate_attack_tree",
    "generate_test_cases",
}
# Mirrors backend.pipeline.runner.FORBIDDEN_FAST_STEPS.
_FORBIDDEN_FAST_STEP_NAMES = {"generate_threats", "gap_analysis"}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM Provider settings
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"
    default_provider: Literal["anthropic", "openai", "ollama", "bedrock"] = "anthropic"
    # AWS Bedrock settings — uses standard boto3 credential chain (env vars,
    # ~/.aws/credentials, IAM roles). No explicit key fields: boto3 handles auth.
    # Empty string defers region to boto3's own resolution order
    # (AWS_DEFAULT_REGION → profile → instance metadata).
    aws_region: str = ""
    aws_profile: str = ""
    default_model: str = "claude-sonnet-4-20250514"
    # Fast model is used for cheaper extraction steps (assets/flows) and
    # enrichment (attack trees / test cases).  Only applies when
    # default_provider == 'anthropic'.  Set FAST_MODEL="" to disable.
    fast_model: str = "claude-haiku-4-5-20251001"
    # Opt-in `output_config.effort` for the *main* Anthropic model (never the
    # fast model). Unset keeps the model's default; claude-sonnet-5 at its
    # default overran 4096 tokens on threat JSON and truncated, `medium`
    # finished comfortably. Older models reject the parameter.
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    default_iterations: int = 3
    # Fast model per non-Anthropic provider (week 4a-2). FAST_MODEL above
    # covers Anthropic; these let "fast" routing apply under any provider.
    # Empty string means "same as main" (no distinct fast provider built).
    fast_model_openai: str = "gpt-4.1-mini"
    fast_model_bedrock: str = ""
    fast_model_ollama: str = ""
    # Per-step fast/main routing override (week 4a-2), e.g.
    # STEP_MODELS='{"extract_flows":"main"}'. Keys are PipelineStep values,
    # merged over the provider's default map in
    # backend.pipeline.runner.resolve_step_models(). Validated eagerly below
    # (step names, "fast"/"main" values, and the forbidden-fast rule) so a
    # bad env var fails at startup, not on the first pipeline run.
    # NoDecode: parsed by parse_step_models below, so a blank `STEP_MODELS=`
    # (as shipped in .env.example) means "no overrides" instead of a JSON error.
    step_models: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)

    # Embedding settings
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # Database settings
    db_path: str = "./data/paranoid.db"

    # MCP settings
    context_link_binary: str = (
        ""  # Empty = auto-detect; set CONTEXT_LINK_BINARY env var to override
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    cors_origins: str = "*"  # Comma-separated origins, or "*" for all

    # Prompt configuration
    summary_max_words: int = 40
    threat_description_min_words: int = 35
    threat_description_max_words: int = 50
    mitigation_min_items: int = 2
    mitigation_max_items: int = 5

    # Pipeline configuration
    max_iteration_count: int = 15
    min_iteration_count: int = 1
    # gt=0: timeout=0 would make _check_time_limit() fire immediately on the
    # first call, aborting every pipeline run before any threat is generated.
    pipeline_timeout_minutes: int = Field(default=30, gt=0)
    # ge/le bounds match the strictest provider: Anthropic caps at 1.0.
    # Values above 1.0 cause an Anthropic API 400 that manifests as a silent
    # rule-engine-only fallback with no indication the config is to blame.
    default_temperature: float = Field(default=0.2, ge=0.0, le=1.0)

    # Rule engine / RAG
    # gt=0: rag_top_k=0 → scored[:0]=[] → rule engine always returns empty,
    # neutering the deterministic safety net with no visible warning.
    rag_top_k: int = Field(default=10, gt=0)

    # Deduplication threshold for rule engine
    similarity_threshold: float = 0.85

    # Pipeline stop conditions
    # Fraction of an iteration's new threats removed by cross-iteration dedup that
    # triggers an early "dedup_saturated" stop.  0.7 = stop when ≥70% of new threats
    # are duplicates.  Distinct from similarity_threshold (which governs *which*
    # threats are duplicates); this governs *whether* saturation fires.
    dedup_saturation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # Runtime iteration floor: early-stop conditions (gap_satisfied, dedup_saturated)
    # are suppressed until at least this many iterations have completed.
    # Distinct from min_iteration_count (input-validation bound on user-supplied values);
    # min_iterations is the execution-time floor applied inside the pipeline runner.
    min_iterations: int = Field(default=1, ge=1)

    # Optional shared secret for PATCH /config.  When set, callers must
    # supply a matching X-Config-Secret header.  Empty string = no auth
    # required (default; safe for local / Docker single-user deployments).
    config_secret: str = ""

    # Auth settings (Phase 0 foundation)
    # JWT signing key. When empty, falls back to PBKDF2 derivation from
    # config_secret (salt "paranoid:jwt:v1"). If config_secret is also empty,
    # an ephemeral per-process key is generated (JWTs invalidated on restart).
    jwt_secret: str = ""
    # Set PARANOID_REQUIRE_AUTH=true to enforce authentication on all routes.
    # When false (default), all requests are treated as instance admin —
    # equivalent to the existing single-user mode. Document: "anyone with
    # network access is admin" when this is false.
    paranoid_require_auth: bool = False
    # PARANOID_ADMIN_PASSWORD: password for the auto-created 'admin' user on
    # first startup (when the users table is empty). If unset, a random
    # password is generated and logged once. Never overwrites an existing user.
    paranoid_admin_password: str = ""

    # CSRF allowlist — comma-separated concrete origins (no "*").  Applied
    # only to non-GET requests that carry an Origin / Referer header; calls
    # without either (CLI, server-to-server) pass through unconditionally.
    # Empty string disables CSRF protection entirely — documented escape
    # hatch for CLI-only setups.
    allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"

    # Git host allowlist for code sources. The built-in set covers
    # github.com, gitlab.com, and bitbucket.org. Additional exact hostnames
    # (no wildcards, no subdomain matching) can be appended here.
    # Example: ADDITIONAL_GIT_HOSTS=git.company.com,git.internal.net
    additional_git_hosts: str = ""

    # Dependency capability engine (npm/JS+TS). See backend/deps/.
    # Kill switch for the whole feature: false rejects a manifest passed to
    # POST /{model_id}/run with 422 and skips code-source auto-detect,
    # without needing a redeploy to disable server-side dependency analysis.
    deps_analysis_enabled: bool = True
    deps_cache_dir: str = "./data/deps_cache"
    deps_max_tarball_mb: int = Field(default=50, gt=0)
    # Process-wide cap on concurrent Semgrep subprocesses across *all*
    # simultaneous pipeline runs — analyze.py's own semaphore only bounds
    # concurrency within a single manifest's sweep (4 packages at a time),
    # so several runs started at once could otherwise spawn unbounded
    # Semgrep processes together.
    deps_max_concurrent_scans: int = Field(default=2, gt=0)
    # Soft cap on DEPS_CACHE_DIR's total size, in GiB. 0 disables eviction
    # (the original unbounded-cache behavior). Checked after every fetch;
    # oldest entries (by `.complete` marker mtime) are evicted first,
    # skipping any entry currently locked by an in-flight fetch.
    deps_cache_max_gb: float = Field(default=10.0, ge=0)
    # Wall-clock budget for the pipeline's ANALYZE_DEPENDENCIES step (resolving,
    # fetching, and scanning every direct dependency). Exceeding it degrades
    # exactly like any other dependency-analysis failure: a warning event,
    # dependency_context=None, and the pipeline continues without it.
    deps_analysis_timeout_seconds: int = Field(default=180, gt=0)
    # Empty = auto-detect via PATH (shutil.which("semgrep")); set SEMGREP_BINARY
    # to override, same pattern as CONTEXT_LINK_BINARY.
    semgrep_binary: str = ""

    # Seed collection filter for the deterministic rule engine.
    # Comma-separated list of collection names (see _KNOWN_SEED_COLLECTIONS).
    # Empty list (default) loads all 16 collections — no behaviour change.
    # Example: SEED_COLLECTIONS=stride,auth,cloud
    seed_collections: list[str] = Field(default_factory=list)

    @field_validator("anthropic_effort", mode="before")
    @classmethod
    def blank_effort_is_unset(cls, v: object) -> object:
        # `ANTHROPIC_EFFORT=` in .env arrives as "" rather than being absent.
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("step_models", mode="before")
    @classmethod
    def parse_step_models(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        if not v.strip():
            return {}
        try:
            return json.loads(v)
        except json.JSONDecodeError as e:
            raise ValueError(
                f'STEP_MODELS must be a JSON object, e.g. {{"extract_flows": "main"}}: {e}'
            ) from e

    @field_validator("step_models")
    @classmethod
    def validate_step_models(cls, v: dict[str, str]) -> dict[str, str]:
        bad_steps = set(v) - _VALID_PIPELINE_STEPS
        if bad_steps:
            raise ValueError(
                f"Unknown pipeline step(s) in STEP_MODELS: {sorted(bad_steps)!r}. "
                f"Valid steps: {sorted(_VALID_PIPELINE_STEPS)}"
            )
        bad_values = {k: val for k, val in v.items() if val not in ("fast", "main")}
        if bad_values:
            raise ValueError(f"STEP_MODELS values must be 'fast' or 'main': {bad_values!r}")
        forbidden_fast = sorted(k for k in v if k in _FORBIDDEN_FAST_STEP_NAMES and v[k] == "fast")
        if forbidden_fast:
            raise ValueError(f"Steps {forbidden_fast} can never be routed to the fast model")
        return v

    @field_validator("seed_collections")
    @classmethod
    def validate_seed_collections(cls, v: list[str]) -> list[str]:
        # Deferred import avoids a circular-import risk at module load time
        # while ensuring the valid set always matches SEED_COLLECTIONS exactly.
        from backend.rules.engine import SEED_COLLECTIONS

        invalid = set(v) - SEED_COLLECTIONS.keys()
        if invalid:
            raise ValueError(
                f"Unknown seed collections: {sorted(invalid)!r}. "
                f"Valid names: {sorted(SEED_COLLECTIONS)}"
            )
        return v


# Global settings instance.
# Wrap Settings() so that an invalid env var produces a readable startup error
# instead of a raw Pydantic ValidationError traceback that buries the field
# path in JSON.  sys.exit(1) is intentional — a misconfigured container should
# fail fast rather than run in a half-broken state.
try:
    settings = Settings()
except ValidationError as _exc:
    _lines = ["[paranoid] Invalid configuration — fix the following env vars and restart:"]
    for _err in _exc.errors():
        _field = " → ".join(str(loc) for loc in _err["loc"])
        _lines.append(f"  {_field}: {_err['msg']}")
    print("\n".join(_lines), file=sys.stderr)
    sys.exit(1)

# Single source of truth for the application version.
# Keep in sync with pyproject.toml when bumping releases.
VERSION = "1.5.0"


# Provider → (env var name, settings attribute / config-table DB key).
# The settings attribute and DB key share the same string by convention;
# the tuple guards against future divergence (e.g. vendor renames).
# Imported by backend.routes.config and backend.main (lifespan hydration)
# so both read the same authoritative mapping.
API_KEY_FIELDS: dict[str, tuple[str, str]] = {
    "anthropic": ("ANTHROPIC_API_KEY", "anthropic_api_key"),
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
}
