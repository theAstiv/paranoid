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
ARG PARANOID_VERSION=1.4.0

# Copy wheel from the wheels-ctx build context.
# In CI, wheels-ctx is overridden with dist/ (local wheel built from checkout).
# In production, wheels-ctx is the empty scratch stage above, so /tmp/wheels/ is empty.
COPY --from=wheels-ctx . /tmp/wheels/
RUN if ls /tmp/wheels/paranoid_cli*.whl 1>/dev/null 2>&1; then \
      pip install --no-cache-dir /tmp/wheels/paranoid_cli*.whl; \
    else \
      pip install --no-cache-dir paranoid-cli==${PARANOID_VERSION}; \
    fi && \
    rm -rf /tmp/wheels/

# Pre-bake the default fastembed model so CI doesn't download it at runtime
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warmup']))"

# entrypoint.sh lives alongside action.yml — within the build context
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
