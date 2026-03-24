# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command to run: `docker compose up`
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Dual Framework Support**: STRIDE (traditional) + MAESTRO (AI/ML) in parallel
- **Structured Input Templates**: XML-tagged component descriptions with assumption enforcement
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Deterministic Fallback**: Rule engine ensures known threats aren't missed
- **MCP Integration**: Pull code context from any MCP server (Antigravity-Link, etc.)
- **CI/CD Ready**: CLI + GitHub Action output SARIF for PR annotations
- **Export Formats**: PDF, JSON, Markdown, SARIF

## Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/paranoid
cd paranoid

# Install package
pip install -e .
```

### Configuration

```bash
# Create .env file
cp .env.example .env

# Edit .env and add your API key
ANTHROPIC_API_KEY=sk-ant-xxx
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514
DEFAULT_ITERATIONS=3
```

### Run Your First Threat Model

**CLI (Recommended):**
```bash
# Run STRIDE threat modeling on example
python -m cli.main run examples/stride-example-api-gateway.md

# Or after installation
paranoid run examples/stride-example-api-gateway.md

# With your own system description
paranoid run my-system.md

# See all options
paranoid run --help
```

**Output:**
```
Configuration:
  Provider: anthropic
  Model: claude-sonnet-4-20250514
  Iterations: 3

[>] summarize: Generating system summary...
[[OK]] summarize: Summary generated: 157 chars
[>] extract_assets: Identifying assets and entities...
[[OK]] extract_assets: Identified 14 assets/entities
...
[[OK]] complete: Pipeline complete: 2 iterations, 17 threats

================================================================================
THREAT MODEL COMPLETE
================================================================================
Total Threats:      17
Iterations:         2
Duration:           115.0 seconds
```

**Test Harness (Development):**
```bash
python test_pipeline.py
# Interactive menu with 4 test scenarios
```

**Python API:**
```python
from backend.pipeline.runner import run_pipeline_for_model
from backend.providers.anthropic import AnthropicProvider
from backend.models.enums import Framework

provider = AnthropicProvider(api_key="your-key")

async for event in run_pipeline_for_model(
    model_id="web-app-001",
    description="E-commerce web application...",
    framework=Framework.STRIDE,
    provider=provider,
    max_iterations=3,
):
    print(f"[{event.step}] {event.message}")
```

## Structured Input Templates

Paranoid supports rich XML-tagged templates for better context and assumption enforcement:

**STRIDE Template** (traditional systems):
- Component description with technology stack, interfaces, data handling
- 6 structured assumption sections (security controls, in-scope, out-of-scope, focus areas, etc.)

**MAESTRO Template** (AI/ML systems):
- Extended component description with mission alignment, agent profile
- 9 structured assumption sections (mission constraints, AI-specific controls, agentic considerations, etc.)

See [examples/](examples/) for full template examples.

## Model Configuration

⚠️ **Important**: Use Claude Sonnet (or newer) for reliable structured output generation.

```bash
# In .env file
DEFAULT_MODEL=claude-sonnet-4-20250514
```

**Models Tested:**
- ❌ `claude-haiku-4-5-20251001` - Fails with JSON parsing errors on complex outputs
- ✅ `claude-sonnet-4-20250514` - Validated end-to-end, reliable for production use

## Architecture

- **Backend**: FastAPI + SQLite + sqlite-vec
- **Frontend**: Planned for Phase 10 (v1.0 is pipeline-only)
- **LLM Providers**: Anthropic / OpenAI / Ollama (protocol-based, swappable)
- **Pipeline**: Plain async functions (no LangChain, no LangGraph)
- **Embeddings**: Local via fastembed (ONNX, BAAI/bge-small-en-v1.5)
- **Models**: Pydantic v2 for all data validation
- **Frameworks**: STRIDE (traditional) + MAESTRO (AI/ML security)

## Documentation

### User Documentation
- [TESTING.md](TESTING.md) - Test suite guide with validation results
- [QUICKSTART.md](QUICKSTART.md) - Step-by-step getting started
- [examples/README.md](examples/README.md) - Structured input template guide
- [STRUCTURED_INPUT_IMPLEMENTATION.md](STRUCTURED_INPUT_IMPLEMENTATION.md) - Feature overview

### Developer Documentation
- [.claude/tasks/build-plan.md](.claude/tasks/build-plan.md) - Complete build plan with phases
- [.claude/rules/CLAUDE.md](.claude/rules/CLAUDE.md) - Project structure and conventions
- [.claude/rules/RULES.md](.claude/rules/RULES.md) - Coding standards
- [.claude/rules/tech-decision-rationale.md](.claude/rules/tech-decision-rationale.md) - Architecture decisions

## Test Results

**Latest Validation (2026-03-24):**
- ✅ Parser validation: PASSING (no API key required)
- ✅ STRIDE pipeline: PASSING (15-25 threats)
- ✅ STRIDE+MAESTRO dual framework: PASSING (24 threats, 213s, 2 iterations)
- ✅ Assumption enforcement: VALIDATED
- ✅ Gap-driven iteration stopping: VALIDATED

See [TESTING.md](TESTING.md) for detailed results.

## License

Apache 2.0

---

## Development Status

**v1.0 Progress:** CLI Phase 1 of 6 (MVP) - Complete ✅

**Completed:**
- ✅ Phase 1: Scaffold (FastAPI + Svelte setup)
- ✅ Phase 2: Persistence layer (SQLite + sqlite-vec)
- ✅ Phase 3: Pydantic models (ported + extended)
- ✅ Phase 4: LLM provider layer (Anthropic, OpenAI, Ollama)
- ✅ Phase 5: STRIDE + MAESTRO prompts
- ✅ Phase 6: Core pipeline (8 nodes, iteration logic, SSE, dual framework, structured input)
- ✅ **CLI Phase 1: MVP** (basic `paranoid run` command, console output)

**Current:**
- 🚧 CLI Phase 2: Configuration Management (interactive wizard, `~/.paranoid/config.json`)

**Next CLI Phases:**
- 📋 CLI Phase 3: JSON Export (simple/full formats, `--output` flag)
- 📋 CLI Phase 4: Structured Input Support (auto-detect, `--maestro` flag)
- 📋 CLI Phase 5: Advanced Options & Polish (`--quiet`, `--verbose`, `paranoid version`)
- 📋 CLI Phase 6: Packaging & Release (PyPI, CHANGELOG, GitHub Actions)

**Future Pipeline Phases:**
- 📋 Phase 6.9: RAG retrieval integration
- 📋 Phase 7: Rule engine + seed data
- 📋 Phase 8: MCP client
- 📋 Phase 9: API routes (REST + SSE)
- 📋 Phase 10: Frontend (Svelte UI)
