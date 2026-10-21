# CLI Reference

## `paranoid run`

Run the threat modeling pipeline against a system description.

```bash
paranoid run <description-file> [OPTIONS]
```

**Arguments**

| Argument | Description |
|----------|-------------|
| `description-file` | Path to a `.md` or `.txt` system description file |

**Options**

| Flag | Default | Description |
|------|---------|-------------|
| `--provider` | config default | LLM provider: `anthropic`, `openai`, `ollama`, `bedrock` |
| `--model` | config default | Model name (e.g. `claude-sonnet-4-20250514`, `gpt-4o`) |
| `--fast-model` | config default | Fast model for the active provider (overrides `FAST_MODEL` / `FAST_MODEL_OPENAI` / …). `--fast-model=` (the `=` form) runs every step on the main model — a bare `--fast-model ""` loses the empty value in PowerShell |
| `--step-model` | provider defaults | `STEP=fast\|main`, repeatable (e.g. `--step-model extract_flows=main`). Replaces `STEP_MODELS` for this run; `generate_threats` and `gap_analysis` can never be `fast` |
| `-n`, `--iterations` | config (`DEFAULT_ITERATIONS`, `3`) | Pipeline iterations (1–15) |
| `--framework` | auto-detect | Force `stride` or `maestro` |
| `--stride-maestro` | off | Run STRIDE + MAESTRO in parallel |
| `--format` | `simple` | Output format: `simple` (JSON), `full` (JSON), `sarif`, `markdown`, `pdf` |
| `-o`, `--output` | none | Write the result to this file (extension added for `sarif`/`markdown`/`pdf`). **Without `-o` no file is written**: every run is saved to the database, and the run prints `Saved as model <id>; export with 'paranoid models export <id> --format …'` |
| `-d`, `--diagram` | — | Architecture diagram: `.png`, `.jpg` (vision), or `.mmd`/`.txt` (Mermaid text). Repeatable — up to 5 diagrams per run, each a named view (e.g. deployment, data flow) |
| `--code` | — | Path to a local repo — grounded threats via context-link MCP |
| `--enrich` | off | Generate attack trees + Gherkin test cases per threat after pipeline |
| `--scoring-method` | `dread` | Risk scoring: `dread`, `cvss` (CVSS v3.1 base score instead) or `both`. The LLM proposes CVSS metrics; scores are always computed by the built-in calculator. Rule-engine and dependency threats get deterministic default vectors |
| `--manifest` | — | `package.json` for dependency capability analysis (needs Semgrep, see [`paranoid deps`](#paranoid-deps)) |
| `--lockfile` | — | `package-lock.json` to pin dependency versions (with `--manifest`) |
| `--deps-source` | `npm` | `npm` (fast) or `both` (adds the npm-tarball vs GitHub-source drift check) |
| `--seed-collections` | all | Restrict the rule engine to named seed collections, repeatable (e.g. `--seed-collections stride --seed-collections auth`) |
| `--seeded-assets` / `--seeded-flows` | — | JSON `AssetsList` / `FlowsList` to use instead of LLM extraction |
| `--seeded-threats` | — | JSON file of known threats to seed into the catalog before iterating |
| `--strict` | off | Exit code 2 if description has error-severity gaps (for CI gates) |
| `-q`, `--quiet` | off | Suppress real-time output, show only summary |
| `-v`, `--verbose` | off | Show detailed event data with complete models |

**Output formats**

| Format | Flag | Size | Use case |
|--------|------|------|----------|
| JSON simple | `simple` (default) | ~2–3 KB | CI dashboards, quick review |
| JSON full | `full` | ~45 KB | Analysis, archival, tool integration |
| SARIF | `sarif` | varies | GitHub Security tab, VS Code, Azure DevOps |
| Markdown | `markdown` | ~4–15 KB | PRs, Confluence, Notion |
| PDF | `pdf` | ~50–200 KB | Security review sign-off, stakeholder sharing |

**Examples**

```bash
# Basic run (saved to the database; no file unless -o)
paranoid run system.md
paranoid run system.md -o threats.json

# With diagram + code context + strict mode
paranoid run system.md --diagram arch.png --code /path/to/repo --strict

# Multiple diagrams (architecture + data flow + deployment), each considered together
paranoid run examples/arsenal-deps/description.md \
  -d examples/arsenal-deps/diagrams/architecture.mmd \
  -d examples/arsenal-deps/diagrams/upload-flow.mmd \
  -d examples/arsenal-deps/diagrams/deployment.png

# Multiple output formats from one run
paranoid run system.md --format sarif -o findings.sarif
paranoid run system.md --format markdown -o report.md

# Force provider/model for a single run
paranoid run system.md --provider openai --model gpt-4o

# Model routing: keep flow extraction on the main model, or turn routing off
paranoid run system.md --step-model extract_flows=main
paranoid run system.md --fast-model=

# Dependency capabilities + CVSS alongside DREAD
paranoid run examples/arsenal-deps/description.md \
  --manifest examples/arsenal-deps/package.json \
  --lockfile examples/arsenal-deps/package-lock.json \
  --deps-source both --scoring-method both

# Dual framework
paranoid run system.md --stride-maestro --iterations 5

# With attack tree enrichment
paranoid run system.md --enrich --format pdf -o enriched-report.pdf
```

---

## `paranoid deps`

Dependency capability scanning for npm packages: what a package *can do* (network, filesystem, process, dynamic code, native addons, …), what changed between two versions, and whether the published tarball matches its GitHub source. Static analysis only; nothing fetched is installed or executed. Requires [Semgrep](https://semgrep.dev) on `PATH` or `SEMGREP_BINARY` (not a pip dependency; the Docker image ships it).

```bash
paranoid deps scan <name>@<version> [--source github|npm|both] [--format console|json] [-o out.json]
paranoid deps diff <name> <old-version> <new-version> [--source github|npm|both] [--format console|json] [-o out.json]
paranoid deps scan-manifest <package.json> [--source github|npm|both] [--format console|json] [-o out.json]
```

| Subcommand | `--source` default | Notes |
|---|---|---|
| `scan` | `both` | One package; with `both`, per-file drift between the npm tarball and the GitHub source |
| `diff` | `npm` | Capability delta between two versions (always from the npm tarballs); `--source both` adds drift for the newer version |
| `scan-manifest` | `npm` | Every direct dependency in a `package.json` |

```bash
paranoid deps scan chalk@5.3.0 --source both
paranoid deps diff ws 8.21.3 8.22.0
paranoid deps scan-manifest package.json --format json -o deps.json
```

What the drift signals mean and what the engine does not catch: see the [README](../README.md#dependency-capability-engine).

---

## `paranoid models`

Inspect and manage saved threat models.

### `paranoid models list`

```bash
paranoid models list [-n N] [--json]
```

| Flag | Description |
|------|-------------|
| `-n`, `--limit N` | Max results, 1–200 (default: 20) |
| `--json` | Machine-readable JSON output |

### `paranoid models show`

```bash
paranoid models show <model-id> [--mitigations | --no-mitigations] [--json]
```

Partial IDs work — first 8 characters are enough.

### `paranoid models export`

```bash
paranoid models export <model-id> --format <fmt> [-o <output>] [--source-file <path>]
```

Run once, export many times. Supported formats: `simple`, `full` (both JSON), `sarif`, `markdown`, `pdf`. Without `-o` the file is written to the current directory as `<id-prefix>_<format><ext>`; missing parent directories in an `-o` path are created.

`--source-file` (SARIF only) sets the repo-relative path GitHub code scanning anchors non-dependency results to — point it at your description file in the repo. Without it, results fall back to a fixed anchor (`threat-model.md`) rather than a logical-only location, which GitHub's code-scanning upload rejects the whole run over.

### `paranoid models delete`

```bash
paranoid models delete <model-id> [-y]
```

`-y` / `--yes` skips the confirmation prompt (for scripting).

### `paranoid models prune`

```bash
paranoid models prune [--older-than DAYS] [--status STATUS] [-y]
```

| Flag | Description |
|------|-------------|
| `--older-than DAYS` | Delete models created more than DAYS days ago (minimum 1) |
| `--status` | Filter by status: `pending`, `completed`, `failed` |
| `-y`, `--yes` | Skip confirmation |

### `paranoid models review`

```bash
paranoid models review <model-id> --status <status> [--source llm|rule_engine] [-y]
```

Set every matching threat's status (`approved`, `rejected`, `pending`, `mitigated`), optionally only threats from one source. Answering "n" at the prompt cancels with exit code 0.

---

## `paranoid config`

### `paranoid config init`

Interactive wizard — sets provider, API key, model, and default iterations. Stores config at `~/.paranoid/config.json`.

```bash
paranoid config init           # first-time setup
paranoid config init --force   # overwrite existing config
```

### `paranoid config show`

Display current configuration (provider, model, iterations).

---

## `paranoid version`

Show version, Python version, dependency list, and current configuration.

---

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (pipeline failure, invalid args, API error) |
| `2` | Strict mode: description has error-severity gaps |

---

## Environment variables

Runtime overrides for all CLI commands. See [configuration.md](configuration.md) for the full list.

```bash
ANTHROPIC_API_KEY=sk-ant-...  paranoid run system.md
DEFAULT_PROVIDER=ollama       paranoid run system.md --model llama3
```
