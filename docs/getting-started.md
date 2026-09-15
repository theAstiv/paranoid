# Getting Started

Get your first threat model in five minutes.

## Prerequisites

- An API key for Anthropic, OpenAI, or a running Ollama instance
- Python 3.12+ (PyPI install) **or** Docker (web UI)

## Install

**PyPI — CLI only (fastest)**

```bash
pip install paranoid-cli
paranoid --version
```

**Docker — full stack (web UI + CLI + API)**

```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid
cp .env.example .env          # then edit .env with your API key
docker compose up --build     # first build: 5–10 min
```

Web UI: `http://localhost:8000/app`  
API docs: `http://localhost:8000/docs`

**Standalone binary — no Python required**

Download from [GitHub Releases](https://github.com/theAstiv/paranoid/releases/latest):

| Platform | File |
|----------|------|
| Linux x86_64 | `paranoid-linux-x64` |
| macOS ARM64 | `paranoid-macos-arm64` |
| Windows x64 | `paranoid-windows-x64.exe` |

## Configure

```bash
paranoid config init    # interactive wizard — sets provider, API key, model, iterations
paranoid config show    # verify settings
```

Or set environment variables directly (see [configuration.md](configuration.md) for all options):

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-xxx
export DEFAULT_PROVIDER=anthropic
export DEFAULT_MODEL=claude-sonnet-4-20250514
```

## Run your first threat model

```bash
# Use the built-in example
paranoid run examples/stride-example-api-gateway.md

# Use your own description
paranoid run my-system.md

# Add an architecture diagram
paranoid run my-system.md --diagram arch.png
```

**Expected output:**

```
[>] summarize: Generating system summary...
[OK] summarize: Summary generated: 196 chars
[>] extract_assets: Identifying assets and entities...
[OK] extract_assets: Identified 14 assets/entities
...
[OK] complete: Pipeline complete: 3 iterations, 23 threats

================================================================================
THREAT MODEL COMPLETE
================================================================================
Total Threats:      23
Iterations:         3
Duration:           92.4 seconds
Output:             my-system_threats.json
```

**Typical runtimes (3 iterations):**

| Provider | Time |
|----------|------|
| Claude Sonnet | 30–60 s |
| GPT-4o | 45–90 s |
| Ollama (local) | 2–5 min |

## Inspect and export results

Every run is saved to SQLite automatically.

```bash
paranoid models list                                 # browse past runs
paranoid models show a1b2c3d4                        # show threats (partial ID works)
paranoid models export a1b2c3d4 --format markdown    # re-export as Markdown
paranoid models export a1b2c3d4 --format sarif       # re-export as SARIF
paranoid models export a1b2c3d4 --format pdf         # re-export as PDF
```

## Next steps

- [CLI Reference](cli-reference.md) — all flags, subcommands, and output formats
- [Configuration](configuration.md) — all environment variables and config options
- [Web UI Guide](web-ui-guide.md) — using the browser interface
- [Authentication](authentication.md) — multi-user setup, RBAC, API tokens
- [GitHub Action](github-action.md) — automated threat modeling in CI/CD
