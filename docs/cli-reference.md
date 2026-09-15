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
| `--provider` | config default | LLM provider: `anthropic`, `openai`, `ollama` |
| `--model` | config default | Model name (e.g. `claude-sonnet-4-20250514`, `gpt-4o`) |
| `--iterations` | `3` | Pipeline iterations (1–15) |
| `--framework` | auto-detect | Force `STRIDE` or `MAESTRO` |
| `--maestro` | off | Run STRIDE + MAESTRO in parallel |
| `--format` | `json` | Output format: `json`, `full`, `sarif`, `markdown`, `pdf` |
| `-o`, `--output` | auto | Output file path (extension added automatically for markdown/pdf) |
| `--diagram` | — | Architecture diagram: `.png`, `.jpg` (vision), or `.mmd` (Mermaid text) |
| `--code` | — | Path to a local repo — grounded threats via context-link MCP |
| `--enrich` | off | Generate attack trees + Gherkin test cases per threat after pipeline |
| `--strict` | off | Exit code 2 if description has error-severity gaps (for CI gates) |
| `--quiet` | off | Suppress real-time output, show only summary |
| `--verbose` | off | Show detailed event data with complete models |
| `--token` | — | PAT for authenticating to a remote Paranoid server |

**Output formats**

| Format | Flag | Size | Use case |
|--------|------|------|----------|
| JSON simple | `json` (default) | ~2–3 KB | CI dashboards, quick review |
| JSON full | `full` | ~45 KB | Analysis, archival, tool integration |
| SARIF | `sarif` | varies | GitHub Security tab, VS Code, Azure DevOps |
| Markdown | `markdown` | ~4–15 KB | PRs, Confluence, Notion |
| PDF | `pdf` | ~50–200 KB | Security review sign-off, stakeholder sharing |

**Examples**

```bash
# Basic run
paranoid run system.md

# With diagram + code context + strict mode
paranoid run system.md --diagram arch.png --code /path/to/repo --strict

# Multiple output formats from one run
paranoid run system.md --format sarif -o findings.sarif
paranoid run system.md --format markdown -o report.md

# Force provider/model for a single run
paranoid run system.md --provider openai --model gpt-4o

# Dual framework
paranoid run system.md --maestro --iterations 5

# With attack tree enrichment
paranoid run system.md --enrich --format pdf -o enriched-report.pdf
```

---

## `paranoid models`

Inspect and manage saved threat models.

### `paranoid models list`

```bash
paranoid models list [--limit N] [--json]
```

| Flag | Description |
|------|-------------|
| `--limit N` | Max results (default: 20) |
| `--json` | Machine-readable JSON output |

### `paranoid models show`

```bash
paranoid models show <model-id> [--no-mitigations] [--json]
```

Partial IDs work — first 8 characters are enough.

### `paranoid models export`

```bash
paranoid models export <model-id> --format <fmt> [-o <output>]
```

Run once, export many times. Supported formats: `json`, `full`, `sarif`, `markdown`, `pdf`.

### `paranoid models delete`

```bash
paranoid models delete <model-id> [--yes]
```

`--yes` skips the confirmation prompt (for scripting).

### `paranoid models prune`

```bash
paranoid models prune [--older-than DAYS] [--status STATUS] [--yes]
```

| Flag | Description |
|------|-------------|
| `--older-than N` | Delete models older than N days |
| `--status` | Filter by status: `failed`, `completed`, `pending` |
| `--yes` | Skip confirmation |

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
PARANOID_TOKEN=pat_...        paranoid models list   # authenticate to remote server
```
