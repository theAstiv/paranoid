# Arsenal demo fixture — MediaDrop

Demo inputs for W3-4 (live end-to-end) and Black Hat India Arsenal demo
scenario 1: "the dependency engine inside a threat model."

**None of this is a real published package or a real security incident.**
`mediadrop-demo` is a fixture; it has no registry entry and nothing in it is
installed or executed. The event-stream incident is a **reconstruction** of
the real, publicly documented 2018 event-stream compromise, built from an
inert payload shape — see `inject_incident.py`'s docstring and
`tests/test_deps_incidents.py`.

## Files

| File | Purpose |
|---|---|
| `description.md` | The system description fed to the pipeline — a small Express/sharp/axios/esbuild image-upload-and-webhook service, written to produce strong architecture threats on its own. |
| `package.json` | 8 real, ordinary direct dependencies (express, axios, sharp, esbuild, jsonwebtoken, zod, uuid, ws) already warm in the local dependency cache. |
| `package-lock.json` | Minimal lockfile — only the top-level `node_modules/<name>` version pins `analyze_manifest()` actually reads, so a warm run is deterministic. |
| `inject_incident.py` | Runs the real dependency engine against the manifest above, builds an inert reconstructed event-stream-style incident package, and runs a real pipeline (or `--no-llm` to just print the delta). |

## Commands

```bash
# Free, local, no LLM call — real npm resolve + real Semgrep scan +
# real delta/drift against the real cached event-stream@3.3.5 profile.
python examples/arsenal-deps/inject_incident.py --source both --no-llm

# Full demo run: real Anthropic pipeline, persists a model you can open
# in the UI. Requires ANTHROPIC_API_KEY.
python examples/arsenal-deps/inject_incident.py --source both

# CLI parity (no incident injection — the CLI path can't inject a fixture
# that never went through npm resolution; see C3 in w3-4-live-e2e-plan.md):
paranoid run examples/arsenal-deps/description.md \
  --manifest examples/arsenal-deps/package.json \
  --lockfile examples/arsenal-deps/package-lock.json \
  --deps-source both \
  -f sarif -o /tmp/mediadrop.sarif
```

## Claim framing

Say "capability visibility + change and discrepancy triage." Say
"reconstructed incident" out loud when showing the event-stream row. Don't
say "catches supply-chain attacks" — that claim needs the real-malware recall
check (H3, bug bash) first.
