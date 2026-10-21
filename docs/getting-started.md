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
mkdir -p data                 # the database lives here; create it before Docker does
docker compose up --build     # first build: 5–10 min
```

The container runs as uid 1000 and keeps its database in `./data` (a bind mount). If Docker creates a missing `./data` itself, it is owned by root and the app can't write to it (the log says `... is not writable by uid 1000`). Create it first, as above; if your own uid isn't 1000 (`id -u`), also run `sudo chown 1000:1000 data`. Docker Desktop on Windows and macOS doesn't enforce this, but a Linux host (or a clone inside WSL) does.

Web UI: `http://localhost:8000/app`  
API docs: `http://localhost:8000/docs`

**Standalone binary — no Python required**

Download from [GitHub Releases](https://github.com/theAstiv/paranoid/releases/latest):

| Platform | File (next release) | File in v1.5.0 |
|----------|------|------|
| Linux x86_64 | `paranoid-linux-x64` | not included — use PyPI or Docker |
| macOS ARM64 | `paranoid-macos-arm64` | `paranoid` |
| Windows x64 | `paranoid-windows-x64.exe` | `paranoid.exe` |

The v1.5.0 binaries predate the dependency engine, ATT&CK mapping and CVSS; for those, use PyPI from source or Docker until the next release.

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

The example files live in the repository, not in the PyPI package. From a clone, run them as shown; after `pip install`, download one first:

```bash
curl -fsSLO https://raw.githubusercontent.com/theAstiv/paranoid/main/examples/stride-example-api-gateway.md
```

```bash
# Use the built-in example (from a clone, or after the download above)
paranoid run examples/stride-example-api-gateway.md   # or: paranoid run stride-example-api-gateway.md

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
Saved as model 3f2a9c1e-…; export with 'paranoid models export 3f2a9c1e-… --format full'
```

No file is written unless you pass `-o`: every run is saved to the local database (`DB_PATH`, default `./data/paranoid.db`). Write a file at run time with `-o threats.json` (or `--format sarif -o findings.sarif`), or export any saved run later with `paranoid models export <id> --format <simple|full|sarif|markdown|pdf>`.

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
