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

## Quick Start

```bash
# Clone and run
git clone https://github.com/yourusername/paranoid
cd paranoid
docker compose up

# Open http://localhost:8000
```

## Architecture

- **Backend**: FastAPI + SQLite + sqlite-vec
- **Frontend**: Svelte + Tailwind CSS
- **LLM Providers**: Anthropic / OpenAI / Ollama (protocol-based)
- **Pipeline**: Plain async functions (no LangChain)
- **Embeddings**: Local via fastembed (ONNX)

## Documentation

- [Build Plan](threat-designer-build-plan.md)
- [Tech Rationale](.claude/rules/tech-decision-rationale.md)
- [Coding Conventions](.claude/rules/RULES.md)

## License

Apache 2.0

---

**Status**: 🚧 Under active development — Phase 1 in progress
