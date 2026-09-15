# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command: `docker compose up`
- **Multi-Provider LLM**: Anthropic, OpenAI, or Ollama (fully local/air-gapped)
- **Dual Framework**: STRIDE (traditional) + MAESTRO (AI/ML) — auto-detected or run in parallel
- **DREAD Risk Scoring**: Automatic 5-dimension scoring (0–10 scale) for severity classification
- **Iterative Refinement**: 1–15 configurable iteration passes with gap analysis
- **Code-as-Input**: Semantic code extraction via context-link MCP (`--code /path/to/repo`)
- **Image-as-Input**: Architecture diagram support (`--diagram arch.png` or `--diagram flow.mmd`)
- **Deterministic Rule Engine**: 362 curated patterns (STRIDE, MAESTRO, OWASP, MITRE ATT&CK/ATLAS, CAPEC, cloud misconfigs) across 16 seed files
- **Export Formats**: JSON, SARIF (GitHub Security), Markdown, PDF
- **Multi-User Collaboration**: Projects with owner/editor/viewer RBAC, threaded comments, assignments, activity log
- **CI/CD Ready**: CLI + GitHub Action with SARIF upload

## Quick Start

```bash
# Install
pip install paranoid-cli

# Configure
paranoid config init

# Run
paranoid run examples/stride-example-api-gateway.md
```

**Docker (web UI + API):**
```bash
git clone https://github.com/theAstiv/paranoid && cd paranoid
cp .env.example .env        # add your API key
docker compose up --build   # web UI at http://localhost:8000/app
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Install, configure, and run your first threat model |
| [CLI Reference](docs/cli-reference.md) | All flags, subcommands, and output formats |
| [Configuration](docs/configuration.md) | All environment variables and config options |
| [Web UI Guide](docs/web-ui-guide.md) | Browser interface walkthrough |
| [Authentication](docs/authentication.md) | Multi-user setup, JWT, PATs, RBAC |
| [API Reference](docs/api-reference.md) | REST API — 79+ route handlers across 12 files |
| [GitHub Action](docs/github-action.md) | Automated threat modeling in CI/CD |
| [Architecture](docs/architecture.md) | System design, pipeline, data model |
| [Deployment](docs/deployment.md) | Docker, PyPI, binary, production hardening |

**Other docs:**
- [CHANGELOG.md](CHANGELOG.md) — Release history
- [CONTRIBUTING.md](CONTRIBUTING.md) — How to contribute
- [SECURITY.md](SECURITY.md) — Vulnerability reporting policy
- [TESTING.md](TESTING.md) — Testing and CI guide
- [Input-template.md](Input-template.md) — Structured input template reference
- [examples/](examples/) — Working STRIDE and MAESTRO examples

## Supported platforms

| Platform | PyPI | Docker | Binary |
|----------|------|--------|--------|
| Ubuntu 20.04+ | ✓ | ✓ | ✓ |
| macOS 11+ ARM64 | ✓ | ✓ | ✓ |
| Windows 10+ | ✓ | ✓ | ✓ |
| WSL2 | ✓ | ✓ | ✓ |

Full platform matrix: [docs/deployment.md](docs/deployment.md)

## Development Status

**v1.5.0+** — Multi-user collaboration release. Non-technical users can open the web app, paste an API key, link a Git repo, and get a threat model — no terminal required.

**Future:** OIDC/SSO federation.

## License

Apache 2.0
