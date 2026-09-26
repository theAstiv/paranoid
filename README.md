# Paranoid

**Open-source, self-hosted, iterative threat modeling powered by LLMs.**

Paranoid takes system descriptions (text, diagrams, or code via MCP) and produces comprehensive STRIDE + MAESTRO threat models through an LLM-powered pipeline with deterministic fallback. Configure 1–15 automated iteration passes, then review threats in a human-in-the-loop approve/reject cycle.

## Features

- **Zero Infrastructure**: SQLite + sqlite-vec. One command: `docker compose up`
- **Multi-Provider LLM**: Anthropic, OpenAI, Ollama (fully local/air-gapped), or AWS Bedrock
- **Dependency Capability Engine**: static-analysis visibility into what an npm dependency can do (network, filesystem, process, dynamic code, native addons), diffed against its own GitHub source — see [below](#dependency-capability-engine)
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

## Dependency capability engine

Static-analysis visibility into what an npm dependency can actually *do* —
network access, filesystem, process spawning, dynamic code, native addons,
and more — compared against its declared GitHub source, so a version bump
that quietly adds a capability shows up before you install it.

```bash
# What can this package do? Fetches npm tarball + GitHub source, runs Semgrep.
paranoid deps scan chalk@5.3.0 --source both

# Did capabilities change between two versions? (this is the *shape* of
# checks that would have caught the real ua-parser-js/event-stream
# supply-chain compromises: a patch release quietly adding a capability
# nothing in the diff would obviously explain. These two specific versions
# are both clean — the actual malicious 0.7.29 was unpublished — this just
# shows the delta computing cleanly against real registry data.)
paranoid deps diff ua-parser-js 0.7.28 0.7.30 --source both

# Sweep every dependency in a package.json / package-lock.json
paranoid deps scan-manifest package.json
```

Requires [Semgrep](https://semgrep.dev) on `PATH` (`pip install semgrep`) —
see `SEMGREP_BINARY`, `DEPS_CACHE_DIR`, `DEPS_MAX_TARBALL_MB` in
[Configuration](docs/configuration.md#dependency-capability-engine). Source is
always fetched read-only; nothing scanned is ever executed or installed.

**What `deps scan` reports:** a `CapabilityProfile` per source — categories
(`network`, `filesystem`, `process`, `dynamic_code`, `native_ffi`,
`persistence`, `authentication`, `environment`, `crypto`, `deserialization`,
`build_install`), each backed by file:line evidence and a real source
snippet, plus any `postinstall`/`preinstall` lifecycle hooks.

**What drift signals mean:** with `--source both`, `paranoid deps scan`
compares the npm tarball against the package's own GitHub source for *one*
version, per file. `paranoid deps diff` is a separate comparison — did this
package's capabilities change between two releases — computed from two
tarball scans; with `--source both` it *additionally* reports drift for the
newer version alone, using the same per-file logic described here:

- **matched / explained_by_sourcemap / explained_by_build** — the tarball
  file's capabilities are all accounted for by the corresponding GitHub file,
  a valid source map, or a declared build step. No signal.
- **relocated** (weak, informational) — a capability new to *that* file but
  already present elsewhere in the package. Worth a look, not proof of
  anything.
- **signal** (strong) — a capability novel to the *entire* GitHub-side scan.
  This is the actionable finding: shipped code does something the published
  source doesn't explain anywhere.
- **generated_unverifiable** (informational) — a file declared by the
  package's own **GitHub** manifest (never the tarball's — the tarball is
  attacker-controlled, so trusting its self-declaration would let an
  attacker excuse any file just by listing it) that a non-npm build
  toolchain (e.g. esbuild's Go build, `cargo build.rs`) produces outside of
  `npm run build`. Can't be verified against source either way; never
  contributes a strong signal.
- **unverifiable** — the tarball file's GitHub counterpart couldn't be
  fetched (a skipped symlink, an over-long path). Excused only against the
  package-wide GitHub category set, so a genuinely novel category still
  signals.
- Added `postinstall`/`preinstall` hooks are graded separately: a
  non-allowlisted addition is a strong signal on its own (the
  `ua-parser-js`-shaped compromise, caught without needing a previous
  version to diff against).

**What it does not catch:**

- **Runtime-fetched payloads.** A package that `fetch()`s and `eval()`s a
  remote payload at runtime shows up as a `network`/`dynamic_code`
  capability — the engine flags that the capability exists, not what the
  fetched code will do.
- **Obfuscation beyond the flagged shapes.** The scanner recognizes specific,
  deliberate evasion patterns (aliased `require`/`Function`, concatenated or
  computed property calls, low-level `process.binding`, etc. — see
  `backend/deps/rules/js/dynamic_code.yaml`), not every possible way to hide
  a call. A sufficiently determined, hand-crafted obfuscation can still slip
  past static analysis; this is capability visibility and drift triage, not
  a guarantee of detection.
- **Generated files with no declared build step**, or generated outside a
  recognized non-npm toolchain marker, still count as ordinary shipped code
  and can trip a signal even when they're legitimately build output.
- **Non-JS/TS package ecosystems.** Layer 1 is npm/JS+TS only; PyPI and
  other ecosystems aren't covered yet.

Read this as "here's what changed and what looks unexplained," not
"this dependency is safe" or "this dependency is malicious" — every signal
is meant to be triaged by a person, not acted on automatically.

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
