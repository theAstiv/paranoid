# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command to run: `docker compose up`
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Dual Framework Support**: STRIDE (traditional) + MAESTRO (AI/ML) auto-detected or run in parallel
- **DREAD Risk Scoring**: Automatic risk assessment with 5 dimensions (0-50 scale) for severity classification
- **Structured Input Templates**: XML-tagged component descriptions with assumption enforcement
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Deterministic Fallback**: Rule engine ensures known threats aren't missed
- **MCP Integration**: Pull code context from any MCP server (Antigravity-Link, etc.)
- **Dual JSON Formats**: Simple (lightweight, ~2KB) or Full (complete models + DREAD, ~45KB)
- **SARIF Export**: GitHub Security integration with PR annotations and Security tab findings
- **CI/CD Ready**: CLI + GitHub Action with SARIF upload for automated threat detection
- **Export Formats**: JSON (simple/full), SARIF, PDF (planned), Markdown (planned)

## Quick Start

### Installation

Choose the installation method that works best for you:

#### Option 1: PyPI (Recommended)

Install from PyPI using pip:

```bash
pip install paranoid-cli
```

Verify installation:

```bash
paranoid --version
```

#### Option 2: Docker

Pull and run the Docker image:

```bash
# Pull latest image
docker pull yourusername/paranoid:latest

# Run threat modeling
docker run --rm \
  -v $(pwd):/workspace \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  yourusername/paranoid:latest \
  paranoid run /workspace/system.md
```

#### Option 3: Standalone Binary (No Python Required)

Download the pre-built binary for your platform from [GitHub Releases](https://github.com/yourusername/paranoid/releases/latest):

**Linux (x86_64):**
```bash
wget https://github.com/yourusername/paranoid/releases/latest/download/paranoid-linux-x64
chmod +x paranoid-linux-x64
./paranoid-linux-x64 --help
```

**macOS (ARM64 - Apple Silicon):**
```bash
wget https://github.com/yourusername/paranoid/releases/latest/download/paranoid-macos-arm64
chmod +x paranoid-macos-arm64
./paranoid-macos-arm64 --help
```

**Windows (x86_64):**
Download `paranoid-windows-x64.exe` from releases and run from Command Prompt or PowerShell.

#### Option 4: From Source (Development)

Clone the repository and install in development mode:

```bash
git clone https://github.com/yourusername/paranoid
cd paranoid
pip install -e .
```

### Configuration

**Option 1: Interactive Wizard (Recommended)**
```bash
# Run the setup wizard
paranoid config init

# Follow the prompts to configure:
#   - LLM Provider (Anthropic/OpenAI/Ollama)
#   - API Key
#   - Model name
#   - Default iterations

# View your configuration
paranoid config show
```

**Option 2: Environment Variables**
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
  Framework: STRIDE
  Input: stride-example-api-gateway.md

  Output: stride-example-api-gateway_threats.json
  Format: simple

[>] summarize: Generating system summary...
[[OK]] summarize: Summary generated: 196 chars
[>] extract_assets: Identifying assets and entities...
[[OK]] extract_assets: Identified 14 assets/entities
[>] extract_flows: Extracting data flows and trust boundaries...
[[OK]] extract_flows: Identified 12 flows, 6 boundaries
[>] generate_threats [iter 1]: Generating threats (iteration 1/3)...
[[OK]] generate_threats [iter 1]: Generated 10 threats
...
[[OK]] complete: Pipeline complete: 2 iterations, 17 threats

================================================================================
THREAT MODEL COMPLETE
================================================================================
Total Threats:      17
Iterations:         2
Duration:           115.0 seconds
Output:             stride-example-api-gateway_threats.json
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

## CLI Commands

### Configuration Management

```bash
# Interactive setup wizard (first-time setup)
paranoid config init

# Reconfigure (overwrite existing config)
paranoid config init --force

# Display current configuration
paranoid config show

# Configuration file location: ~/.paranoid/config.json
```

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
paranoid run system.md --format sarif

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

# Help
paranoid --help
paranoid run --help
paranoid config --help
```

### Version Information

```bash
# Show version, Python version, dependencies, and current configuration
paranoid version
```

### Output Formats

Paranoid supports multiple export formats optimized for different use cases:

#### JSON Output

**Simple Format** (default, ~2-3 KB):
- Lightweight threat summaries (name, category, target, impact, likelihood, mitigation count)
- Execution metadata (iterations, duration, threat counts)
- Perfect for: CI/CD dashboards, quick reviews, status tracking
- No events, no complete Pydantic models

**Full Format** (~45 KB):
- Complete Pydantic models (Assets, Flows, Threats with all fields)
- DREAD risk assessment scores (Damage, Reproducibility, Exploitability, Affected Users, Discoverability)
- Full pipeline event audit trail
- Perfect for: Detailed analysis, archival, integration with other tools

```bash
# Simple format (default)
paranoid run system.md -o threats.json

# Full format
paranoid run system.md --format full -o complete.json
```

**Example Simple Format:**
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

**Example Full Format:**
```json
{
  "threats": [
    {
      "name": "JWT Token Forgery",
      "stride_category": "Spoofing",
      "description": "Malicious actor can forge JWT tokens...",
      "target": "API Gateway",
      "impact": "Complete authentication bypass",
      "likelihood": "Medium",
      "dread": {
        "damage": 10,
        "reproducibility": 7,
        "exploitability": 5,
        "affected_users": 10,
        "discoverability": 5
      },
      "mitigations": [
        "Implement strict JWT signature validation",
        "Monitor for suspicious token patterns",
        "Implement token blacklisting capability"
      ]
    }
  ],
  "assets": [...],
  "flows": [...],
  "events": [...]
}
```

#### SARIF Export (GitHub Security Integration)

**SARIF 2.1.0** format for GitHub Security, GitLab, VS Code, and Azure DevOps integration:

```bash
# Export to SARIF
paranoid run system.md --format sarif -o threats.sarif
```

**Features:**
- Threats appear in GitHub Security tab
- PR annotations for each finding
- Severity mapping from DREAD scores (error/warning/note)
- Mitigations as actionable fixes (tagged as Preventive/Detective/Containment)
- Full STRIDE category metadata with mitigation guidance

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

**Example SARIF Output:**

Threats appear in GitHub with:
- **Rule ID**: `stride/tampering`, `stride/spoofing`, etc.
- **Level**: `error` (Critical/High), `warning` (Medium), `note` (Low)
- **Location**: Source file + logical location (threatened component)
- **Fixes**: Mitigations with type labels (`[P]` Preventive, `[D]` Detective, `[C]` Containment)
- **Help Text**: Category-specific guidance with markdown formatting

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

**v1.0 Release Candidate - CLI Complete!** ✅

**Completed:**
- ✅ Phase 1: Scaffold (FastAPI + Svelte setup)
- ✅ Phase 2: Persistence layer (SQLite + sqlite-vec)
- ✅ Phase 3: Pydantic models (ported + extended)
- ✅ Phase 4: LLM provider layer (Anthropic, OpenAI, Ollama)
- ✅ Phase 5: STRIDE + MAESTRO prompts
- ✅ Phase 6: Core pipeline (8 nodes, iteration logic, SSE, dual framework, structured input)
- ✅ **CLI Phase 1: MVP** (basic `paranoid run` command, console output)
- ✅ **CLI Phase 2: Configuration Management** (interactive wizard, `~/.paranoid/config.json`)
- ✅ **CLI Phase 3: JSON Export** (simple/full formats, `--output` flag, DREAD scoring)
- ✅ **CLI Phase 4: Structured Input Support** (auto-detect, `--maestro` flag)
- ✅ **CLI Phase 5: Advanced Options & Polish** (`--quiet`, `--verbose`, `--iterations`, `--framework`, `paranoid version`)
- ✅ **CLI Phase 6: Packaging & Release** (PyPI, Docker Hub, standalone binaries, GitHub Actions)

**Ready for Release:**
- 🎉 CLI is production-ready (6/6 phases complete, 100%)
- 🎉 Available on PyPI as `paranoid-cli`
- 🎉 Docker images on Docker Hub (multi-arch: amd64, arm64)
- 🎉 Standalone binaries for Linux, macOS, Windows

**Future Features (v2.0+):**
- 📋 Phase 6.9: RAG retrieval integration
- 📋 Phase 7: Rule engine + seed data
- 📋 Phase 8: MCP client
- 📋 Phase 9: API routes (REST + SSE)
- 📋 Phase 10: Frontend (Svelte UI)
