# GitHub Action

The official Paranoid action runs threat modeling in CI and uploads SARIF results to the GitHub Security tab.

## Usage

```yaml
name: Threat Model

on: [push, pull_request]

permissions:
  security-events: write
  contents: read

jobs:
  threat-model:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Paranoid threat modeling
        id: paranoid
        uses: theAstiv/paranoid@v1.5.0
        with:
          description-file: docs/system-description.md
          provider: anthropic
          api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          framework: STRIDE
          iterations: 3

      - name: Upload SARIF to GitHub Security tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: ${{ steps.paranoid.outputs.sarif-file }}
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `description-file` | Yes | — | Path to system description (`.md` or `.txt`), relative to repo root |
| `provider` | No | `anthropic` | LLM provider: `anthropic`, `openai`, or `ollama` |
| `api-key` | No* | — | Provider API key; omit for Ollama |
| `model` | No | provider default | Model override (e.g. `claude-sonnet-4-20250514`, `gpt-4o`) |
| `framework` | No | `STRIDE` | Threat framework: `STRIDE` or `MAESTRO` |
| `iterations` | No | `3` | Pipeline iterations (1–15) |
| `sarif-output` | No | `paranoid-results.sarif` | SARIF output file path |
| `strict` | No | `false` | Exit code 2 on error-severity description gaps |
| `fail-on-findings` | No | `false` | Fail the step if any threats are found |

*Required for `anthropic` and `openai` providers.

## Outputs

| Output | Description |
|--------|-------------|
| `sarif-file` | Path to the generated SARIF file |
| `total-threats` | Number of threats found |
| `model-id` | UUID of the saved threat model (query via API) |

## Examples

### Strict mode — fail on description gaps

```yaml
- uses: theAstiv/paranoid@v1.5.0
  with:
    description-file: docs/system-description.md
    provider: anthropic
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    strict: "true"
```

Exit code 2 if the description is missing critical sections (auth, trust boundaries, data flows, external integrations).

### Fail if threats are found

For high-security workflows where any new threat in a PR is a blocker:

```yaml
- uses: theAstiv/paranoid@v1.5.0
  with:
    description-file: docs/system-description.md
    provider: anthropic
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    fail-on-findings: "true"
```

### MAESTRO for AI/ML systems

```yaml
- uses: theAstiv/paranoid@v1.5.0
  with:
    description-file: docs/ml-system.md
    provider: anthropic
    api-key: ${{ secrets.ANTHROPIC_API_KEY }}
    framework: MAESTRO
    iterations: 5
```

### OpenAI provider

```yaml
- uses: theAstiv/paranoid@v1.5.0
  with:
    description-file: docs/system.md
    provider: openai
    api-key: ${{ secrets.OPENAI_API_KEY }}
    model: gpt-4o
```

## SARIF integration

The SARIF file maps each threat to a SARIF result:

- **ruleId**: STRIDE/MAESTRO category (e.g. `STRIDE/Tampering`)
- **level**: mapped from DREAD score (critical → error, high → warning, medium → note, low → note)
- **message**: threat description
- **locations**: references the description file

Results appear in the **Security** tab under **Code scanning alerts** and as **PR annotations** on relevant lines.

## Version pinning

Pin to a specific version tag to avoid unexpected behavior changes:

```yaml
uses: theAstiv/paranoid@v1.5.0   # pinned
uses: theAstiv/paranoid@v1        # floating major (receives non-breaking updates)
```
