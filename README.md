# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command to run: `docker compose up`
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Deterministic Fallback**: Rule engine ensures known threats aren't missed
- **MCP Integration**: Pull code context from any MCP server (Antigravity-Link, etc.)
- **CI/CD Ready**: CLI + GitHub Action output SARIF for PR annotations
- **Export Formats**: PDF, JSON, Markdown, SARIF

## Quick Start (CLI)

```bash
# Install
pip install -e .

# Set API key
export ANTHROPIC_API_KEY=your-key-here

# Run threat modeling
paranoid run --description "Web app with user authentication and PostgreSQL database" \
  --provider anthropic --iterations 3

# View results
paranoid list
paranoid show <model-id>
```

## Quick Start (Docker)

```bash
# Clone and run
git clone https://github.com/yourusername/paranoid
cd paranoid
docker compose up

# Health check: http://localhost:8000/health
```

## Architecture

- **Backend**: FastAPI + SQLite + sqlite-vec
- **Frontend**: Planned for v2.0 (v1.0 is CLI-only)
- **LLM Providers**: Anthropic / OpenAI / Ollama (protocol-based)
- **Pipeline**: Plain async functions (no LangChain)
- **Embeddings**: Local via fastembed (ONNX)
- **Models**: Pydantic v2

## Documentation

- [Build Plan](build-plan.md)
- [Tech Rationale](tech-decision-rationale.md)
- [Coding Conventions](RULES.md)
- [Development Guide](CLAUDE.md)

## License

Apache 2.0

---

**Status**: 🚧 v1.0 Development — Phases 1-4 complete (Persistence + Models + Providers)
**Next**: Phase 5 — Prompt Templates
