# syntax=docker/dockerfile:1
#
# Paranoid GitHub Action container
#
# The build context for Docker container actions is the directory containing
# action.yml (i.e. action/), not the repository root.
#
# Two install paths:
#   CI:         build-contexts=wheels-ctx=dist  →  installs from local wheel (no PyPI dependency)
#   Production: no build-contexts override       →  installs from PyPI (pinned PARANOID_VERSION)
#
# Pre-bakes the fastembed embedding model so the first action run does not
# spend ~30 s downloading 130 MB during the CI step.

# Fallback "wheels" context — overridden by --build-context wheels-ctx=<path> in CI.
# FROM scratch produces an empty image; COPY --from=wheels-ctx then copies nothing,
# and the RUN below falls through to the PyPI install path.
FROM scratch AS wheels-ctx

FROM python:3.12-slim

WORKDIR /app

# Pin to the version that matches the action tag.
# Update this ARG on every release (also bump pyproject.toml).
ARG PARANOID_VERSION=1.6.0

# Copy wheel from the wheels-ctx build context.
# In CI, wheels-ctx is overridden with dist/ (local wheel built from checkout).
# In production, wheels-ctx is the empty scratch stage above, so /tmp/wheels/ is empty.
COPY --from=wheels-ctx . /tmp/wheels/
# The [bedrock] extra (boto3) lets `provider: bedrock` work.
RUN if ls /tmp/wheels/paranoid_cli*.whl 1>/dev/null 2>&1; then \
      whl=$(ls /tmp/wheels/paranoid_cli*.whl | head -n1) && \
      pip install --no-cache-dir "${whl}[bedrock]"; \
    else \
      pip install --no-cache-dir "paranoid-cli[bedrock]==${PARANOID_VERSION}"; \
    fi && \
    rm -rf /tmp/wheels/

# Semgrep powers the dependency capability scanner (the `manifest` input). Same
# pin and isolated venv as the main Dockerfile: installed next to paranoid-cli,
# its pinned transitive deps (opentelemetry, click, ...) would shift the app's.
ARG SEMGREP_VERSION=1.178.0
RUN python3 -m venv /opt/semgrep-venv && \
    /opt/semgrep-venv/bin/pip install --no-cache-dir "semgrep==${SEMGREP_VERSION}"
ENV SEMGREP_BINARY=/opt/semgrep-venv/bin/semgrep

# Pre-bake the default fastembed model so CI doesn't download it at runtime
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))" \
    || echo "[warn] fastembed pre-download failed — model will be fetched on first run"

# entrypoint.sh lives alongside action.yml — within the build context
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
