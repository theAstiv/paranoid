# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command to run: `docker compose up`[coming soon]
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Dual Framework Support**: STRIDE (traditional) + MAESTRO (AI/ML) auto-detected or run in parallel
- **DREAD Risk Scoring**: Automatic risk assessment with 5 dimensions (0-50 scale) for severity classification
- **Structured Input Templates**: Tagged templates for component descriptions with assumption enforcement in the prompts
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Deterministic Fallback**: Rule engine ensures known threats aren't missed[Coming Soon]
- **MCP Integration**: Pull code context from any MCP server (context-link, etc.)[Coming Soon]
- **Export Formats**: JSON (simple/full), SARIF (GitHub Security integration)
- **CI/CD Ready**: CLI + GitHub Action with SARIF upload for automated threat detection

## Quick Start

### Step 1: Install

Choose the method that works best for you:

**PyPI (Recommended):**
```bash
pip install paranoid-cli
paranoid --version
```

**Docker [Coming Soon]:**
```bash
docker pull theastiv/paranoid:latest

docker run --rm \
  -v $(pwd):/workspace \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  theastiv/paranoid:latest \
  paranoid run /workspace/system.md
```

**Standalone Binary (No Python Required):**

Download the pre-built binary for your platform from [GitHub Releases](https://github.com/theAstiv/paranoid/releases/latest):

| Platform | Binary |
|----------|--------|
| Linux x86_64 | `paranoid-linux-x64` |
| macOS ARM64 (Apple Silicon) | `paranoid-macos-arm64` |
| Windows x64 | `paranoid-windows-x64.exe` |

```bash
# Linux/macOS
chmod +x paranoid-linux-x64
./paranoid-linux-x64 --help
```

**From Source (Development):**
```bash
git clone https://github.com/theAstiv/paranoid
cd paranoid
pip install -e .
```

### Step 2: Configure

**Option A: Interactive Wizard (Recommended)**
```bash
paranoid config init

# Follow prompts to configure:
#   - LLM Provider (Anthropic/OpenAI/Ollama)
#   - API Key
#   - Model name
#   - Default iterations

paranoid config show
```

**Option B: Environment Variables**
```bash
cp .env.example .env
```

Edit `.env` and add your provider configuration:

```bash
# Anthropic (Recommended)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxx
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514

# OR OpenAI
OPENAI_API_KEY=sk-xxxxxxxxx
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=gpt-4-turbo

# OR Ollama (fully local, no API key)
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_PROVIDER=ollama
DEFAULT_MODEL=llama3
```

### Step 3: Run Your First Threat Model

```bash
# Run with an example
paranoid run examples/stride-example-api-gateway.md

# With your own system description
paranoid run my-system.md

# See all options
paranoid run --help
```

**Expected Output:**
```
Configuration:
  Provider: anthropic
  Model: claude-sonnet-4-20250514
  Iterations: 3
  Framework: STRIDE

[>] summarize: Generating system summary...
[OK] summarize: Summary generated: 196 chars
[>] extract_assets: Identifying assets and entities...
[OK] extract_assets: Identified 14 assets/entities
[>] extract_flows: Extracting data flows and trust boundaries...
[OK] extract_flows: Identified 12 flows, 6 boundaries
[>] generate_threats [iter 1]: Generating threats (iteration 1/3)...
[OK] generate_threats [iter 1]: Generated 10 threats
...
[OK] complete: Pipeline complete: 2 iterations, 17 threats

================================================================================
THREAT MODEL COMPLETE
================================================================================
Total Threats:      17
Iterations:         2
Duration:           115.0 seconds
Output:             stride-example-api-gateway_threats.json
```

**Expected Runtime:**
- Claude Sonnet: ~30-60 seconds (3 iterations)
- GPT-4: ~45-90 seconds (3 iterations)
- Ollama (local): 2-5 minutes (depends on hardware)

## CLI Reference

### Running Threat Models

```bash
# Basic usage (auto-detects framework from input)
paranoid run system.md

# Structured templates (auto-detects STRIDE vs MAESTRO)
paranoid run examples/stride-example-api-gateway.md
paranoid run examples/maestro-example-rag-chatbot.md

# JSON output (simple format - lightweight, ~2-3 KB)
paranoid run system.md --output threats.json

# JSON output (full format - complete models + DREAD + events, ~45 KB)
paranoid run system.md --format full -o complete.json

# SARIF export for GitHub Security integration
paranoid run system.md --format sarif -o threats.sarif

# Force dual framework (STRIDE + MAESTRO in parallel)
paranoid run system.md --maestro

# Override iteration count (1-15)
paranoid run system.md --iterations 7

# Override framework auto-detection
paranoid run system.md --framework MAESTRO

# Quiet mode (suppress real-time output, show only summary)
paranoid run system.md --quiet

# Verbose mode (show detailed event data with complete models)
paranoid run system.md --verbose
```

### Configuration Management

```bash
# Interactive setup wizard
paranoid config init

# Reconfigure (overwrite existing config)
paranoid config init --force

# Display current configuration
paranoid config show

# Config file location: ~/.paranoid/config.json
```

### Version Info

```bash
# Show version, Python version, dependencies, and current configuration
paranoid version
```

## Output Formats

### JSON Simple (default, ~2-3 KB)

Lightweight threat summaries for CI/CD dashboards and quick reviews.

```json
{
  "execution": {
    "total_threats": 17,
    "iterations_completed": 2,
    "duration_seconds": 115.0
  },
  "threats": [
    {
      "name": "JWT Token Forgery",
      "category": "Spoofing",
      "target": "API Gateway",
      "impact": "Complete authentication bypass",
      "likelihood": "Medium",
      "mitigation_count": 3
    }
  ]
}
```

### JSON Full (~45 KB)

Complete Pydantic models with DREAD scores and full pipeline event audit trail. Suitable for detailed analysis, archival, and integration with other tools.

```bash
paranoid run system.md --format full -o complete.json
```

### SARIF (GitHub Security Integration)

SARIF 2.1.0 format for GitHub Security tab, GitLab, VS Code, and Azure DevOps:

```bash
paranoid run system.md --format sarif -o threats.sarif
```

**GitHub Actions Integration:**

```yaml
name: Threat Model

on: [push, pull_request]

jobs:
  threat-model:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run threat modeling
        run: |
          pip install paranoid-cli
          paranoid run system.md --format sarif -o threats.sarif
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: threats.sarif
```

## Structured Input Templates

Paranoid supports rich XML-tagged templates for better context and assumption enforcement. See [Input-template.md](Input-template.md) for the full template reference and [examples/](examples/) for working examples.

**STRIDE Template** (traditional systems): Component description with technology stack, interfaces, data handling, and 6 structured assumption sections.

**MAESTRO Template** (AI/ML systems): Extended component description with mission alignment, agent profile, and 9 structured assumption sections.

## Model Configuration

**Use Claude Sonnet (or newer) for reliable structured output generation.**

| Model | Status | Notes |
|-------|--------|-------|
| `claude-sonnet-4-20250514` | Recommended | Validated end-to-end, reliable for production |
| `claude-haiku-4-5-20251001` | Not recommended | Fails with JSON parsing errors on complex outputs |
| GPT-4 Turbo | Supported | Works well, slightly slower |
| Ollama (Llama 3 70B+) | Supported | Fully local, no external API calls |

## Architecture

- **Backend**: FastAPI + SQLite + sqlite-vec
- **Frontend**: Planned (v1.0 is CLI-only)
- **LLM Providers**: Anthropic / OpenAI / Ollama (protocol-based, swappable)
- **Pipeline**: Plain async functions (no LangChain, no LangGraph)
- **Embeddings**: Local via fastembed (ONNX, BAAI/bge-small-en-v1.5)
- **Models**: Pydantic v2 for all data validation
- **Frameworks**: STRIDE (traditional) + MAESTRO (AI/ML security)

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

## Testing

```bash
# Run unit/integration tests (no API key required)
pytest tests/ -v

# Run pipeline integration test (requires API key)
python test_pipeline.py

# Validate structured input parser (no API key required)
python examples/test_structured_input.py

# Lint
ruff check backend/ cli/
ruff format backend/ cli/
```

**Validated Results (2026-03-24):**
- Parser validation: PASSING (no API key required)
- STRIDE pipeline: PASSING (15-25 threats)
- STRIDE+MAESTRO dual framework: PASSING (24 threats, 213s, 2 iterations)
- Assumption enforcement: VALIDATED
- Gap-driven iteration stopping: VALIDATED

## Troubleshooting

**Authentication errors:**
- Check your API key is correct in `.env` or `~/.paranoid/config.json`
- For Anthropic, ensure billing is set up and key starts with `sk-ant-api03-`

**Module not found:**
```bash
pip install -e .  # or: pip install paranoid-cli
```

**Ollama connection refused:**
```bash
ollama serve  # start Ollama first, then run paranoid
```

**macOS binary "developer cannot be verified":**
```bash
xattr -d com.apple.quarantine paranoid-macos-arm64
```

**Windows "Windows protected your PC":**
Click "More info" then "Run anyway", or add an exception in Windows Defender.

## Platform Support

| Platform | PyPI | Docker | Binary |
|----------|------|--------|--------|
| Ubuntu 20.04+ | Yes | Yes | Yes |
| Debian 11+ | Yes | Yes | Yes |
| RHEL 8+ | Yes | Yes | Yes |
| macOS 11+ (Intel) | Yes | Yes | No |
| macOS 11+ (ARM64) | Yes | Yes | Yes |
| Windows 10+ | Yes | Yes | Yes |
| WSL2 | Yes | Yes | Yes |

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — Release history
- [Input-template.md](Input-template.md) — Structured input template reference
- [examples/](examples/) — Working STRIDE and MAESTRO examples
- [RELEASE.md](RELEASE.md) — Maintainer release checklist

**Developer docs:**
- [.claude/rules/CLAUDE.md](.claude/rules/CLAUDE.md) — Project structure and conventions
- [.claude/rules/RULES.md](.claude/rules/RULES.md) — Coding standards
- [.claude/rules/tech-decision-rationale.md](.claude/rules/tech-decision-rationale.md) — Architecture decisions

## Development Status

**v1.1.0** — CLI production-ready, available on [PyPI](https://pypi.org/project/paranoid-cli/) and as standalone binaries.

**Completed:** Core pipeline (8 nodes, iteration logic, SSE, dual framework), LLM providers (Anthropic/OpenAI/Ollama), STRIDE + MAESTRO prompts, structured input templates, JSON + SARIF export, DREAD scoring, CLI with config wizard, packaging and release automation.

**Future (v2.0+):** RAG retrieval integration, deterministic rule engine, MCP client, REST API routes, frontend (Svelte UI).

## License

Apache 2.0
