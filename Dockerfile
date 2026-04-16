# syntax=docker/dockerfile:1
#
# Multi-stage Dockerfile for Paranoid
#
# Stages
# ──────
#   context-link-fetcher   Downloads the context-link binary from GitHub releases
#   frontend-builder       Svelte + Tailwind SPA
#   final                  Python 3.12 runtime — serves API + static frontend
#
# Build arguments
# ───────────────
#   CONTEXT_LINK_VERSION   context-link release to download (default: 1.0.0)
#   EMBEDDING_MODEL        fastembed model to pre-bake (default: BAAI/bge-small-en-v1.5)
#
# Building without context-link (offline)
# ────────────────────────────────────────
# 1. Comment out the context-link-fetcher stage below.
# 2. Remove the COPY --from=context-link-fetcher line in the final stage.
# 3. Mount your own binary at runtime:
#      docker run -v /path/to/context-link:/app/bin/context-link:ro ...
#    or set CONTEXT_LINK_BINARY to a PATH-accessible binary.

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — context-link binary (downloaded from GitHub releases)
# Provides the MCP code-extraction server used by the --code flag.
# Release page: https://github.com/context-link-mcp/context-link/releases
# TARGETARCH is set automatically by Docker (amd64 | arm64).
# ─────────────────────────────────────────────────────────────────────────────
FROM alpine:3.20 AS context-link-fetcher

ARG CONTEXT_LINK_VERSION=1.0.0
ARG TARGETARCH

RUN apk add --no-cache curl tar && \
    curl -fsSL \
        "https://github.com/context-link-mcp/context-link/releases/download/v${CONTEXT_LINK_VERSION}/context-link_${CONTEXT_LINK_VERSION}_linux_${TARGETARCH}.tar.gz" \
        -o /tmp/cl.tar.gz && \
    tar -xzf /tmp/cl.tar.gz -C /tmp && \
    install -m 755 /tmp/context-link /usr/local/bin/context-link

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Svelte + Tailwind frontend
# ─────────────────────────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Python backend (final image)
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

# curl is required for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (uid 1000)
RUN useradd -m -u 1000 -s /bin/bash app

WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy pyproject.toml first so this layer is cached independently of
# source-code changes.  Re-runs only when declared dependencies change.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# ── Application source ────────────────────────────────────────────────────────
COPY backend/ ./backend/
COPY seeds/   ./seeds/
COPY cli/     ./cli/

# ── Built artifacts ───────────────────────────────────────────────────────────
COPY --from=frontend-builder     /app/frontend/dist ./frontend/dist
COPY --from=context-link-fetcher /usr/local/bin/context-link ./bin/context-link

# ── fastembed model pre-download ──────────────────────────────────────────────
# Bakes the embedding model (~130 MB) into the image so the first
# container startup doesn't require network access or a long wait.
# On failure (air-gapped build) the model is downloaded at first startup.
# Must match config.py's embedding_model default and the EMBEDDING_MODEL env var.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
RUN python3 -c "\
from fastembed import TextEmbedding; \
TextEmbedding('${EMBEDDING_MODEL}', cache_dir='/app/.cache/fastembed')" \
    || echo "[warn] fastembed pre-download failed — model will be fetched on first startup"

# ── Permissions ───────────────────────────────────────────────────────────────
RUN mkdir -p /app/data && \
    chown -R app:app /app/data /app/.cache /app/bin /app/frontend

USER app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    DB_PATH=/app/data/paranoid.db

# Extra start_period to allow DB init + seed loading on first boot
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
