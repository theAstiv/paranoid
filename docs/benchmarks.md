# Benchmarks

Measured results for Paranoid's pipeline, model routing, dependency capability engine and multi-diagram input. Each section gives its date, the code it ran on, the models, the sample size and how to reproduce it.

## Read this first

- **Small samples.** Most LLM measurements are n = 1–3 runs per arm. LLM output varies run to run (whole-run cost varied ±17% within a single arm), so treat single-run numbers as indicative, not as averages.
- **One fixture.** Unless stated otherwise, runs use [`examples/arsenal-deps/`](../examples/arsenal-deps/): "MediaDrop", a fictional upload service with 8 direct npm dependencies. Results on other systems will differ.
- **Dated models.** Anthropic runs used `claude-sonnet-5` (main) and `claude-haiku-4-5-20251001` (fast), with `ANTHROPIC_EFFORT=medium`. OpenAI runs used `gpt-4.1` and `gpt-4.1-mini`. Newer models will change the numbers.
- **Costs are modelled, not billed.** Dollar figures multiply recorded token counts (from `threat_models.usage_summary`) by Anthropic list prices read on the date given. Bedrock and Vertex pricing differs.
- **What isn't measured yet** is listed in the last section. In particular, the dependency engine has **no real-malware detection rate yet**. Don't read anything below as "catches supply-chain attacks".

---

## 1. Model routing (fast/main per step)

**2026-10-05 · `main` @ `d0f0994` · Anthropic · n = 3 runs per arm**

Routing `extract_assets` and `extract_flows` to Claude Haiku 4.5, with everything else on Claude Sonnet 5:

| Routed step | Sonnet 5 (3 runs) | Haiku 4.5 (3 runs) | Cost | Median duration per run |
|---|---|---|---|---|
| `extract_assets` | $0.0608 | $0.0238 | −61% | 14.0 s → 10.6 s |
| `extract_flows` | $0.1721 | $0.0570 | −67% | 34.2 s → 23.8 s |
| **Both** | **$0.2328** | **$0.0808** | **−65%** | **47.8 s → 34.2 s (−28%)** |

- **Per run:** those two steps are about 25% of a run's cost without `--enrich`, so routing saves **about 16% per run** on this fixture. That figure is modelled from the per-step numbers; it isn't an observed whole-run difference.
- **Why not compare whole runs:** whole-run cost differed by 0.58% between arms, well inside the ±17% spread within one arm, which comes almost entirely from `generate_threats` and `gap_analysis`. Routing never touches those two steps: they always run on the main model.
- **Output:** Haiku extracted more flows (17/16/18 → 22/23/21) and consistently gave credential handling its own flows (secret/credential flows 5/4/5 → 10/11/7). Whether that changes downstream threat quality wasn't assessed.
- **Prices used** (per million tokens, read 2026-10-05): Sonnet 5 $2 in / $10 out / $0.20 cache read / $2.50 cache write; Haiku 4.5 $1 / $5 / $0.10 / $1.25.
- **Limits:**
  - Only 2 of the 4 fast-eligible steps ran, since attack trees and test cases need `--enrich`.
  - One pre-flight gap-check call per run (about 4–6% of run cost) wasn't counted in either arm. It's counted since #116.

**Reproduce** (OFF arm shown; the ON arm drops `FAST_MODEL=""`). Per-step usage is in `threat_models.usage_summary` in the scratch DB:

```bash
DB_PATH=./data/routing-measure.db ANTHROPIC_EFFORT=medium FAST_MODEL="" \
  paranoid run examples/arsenal-deps/description.md \
  --manifest examples/arsenal-deps/package.json \
  --lockfile examples/arsenal-deps/package-lock.json \
  --deps-source npm -n 3 --format full -o off-1.json
```

---

## 2. End-to-end pipeline timings

**2026-10-01 · Anthropic `claude-sonnet-5`, effort `medium` · STRIDE · n = 1 per row**

| Run | Path | Dependency cache | Mode | Dependency analysis | Total | Iterations | Threats (LLM / rules / deps) |
|---|---|---|---|---|---|---|---|
| B1 | API | cold | `npm` | 29.2 s | 169 s | 2 | 28 (11 / 10 / 7) |
| B2 | API | warm | `npm` | 25.9 s | 146 s | 1 | 27 (10 / 10 / 7) |
| B3 | API | cold | `both` | 61.6 s | 296 s | 3 | 35 (18 / 10 / 7) |
| B4 | API | warm | `both` | 51.2 s | 200 s | 1 | 27 (10 / 10 / 7) |
| B8 | API | — | no manifest | — | 244 s | 3 | 26 (16 / 10 / 0) |

- **The dependency cache barely helps:** warm vs cold saves 4–10 s, because Semgrep scanning dominates, not the download. A pre-warmed cache matters for offline use, not speed.
- **Deep mode** (`--deps-source both`, comparing the npm tarball with GitHub source) adds about 30 s for 8 packages, well inside the default 180 s budget.
- **Effort matters most for wall time:** a full run took 169 s at `ANTHROPIC_EFFORT=medium` against 517 s at the default effort on `claude-sonnet-5`.
- Iteration counts differ because the pipeline stops early once gap analysis is satisfied or new threats are mostly duplicates.

---

## 3. Dependency capability engine

### 3.1 Benchmark gates (43 popular npm packages)

**2026-09-26 · Windows and Linux · each package at its `latest` tag on that date**

| Gate | Windows | Linux |
|---|---|---|
| Packages scanned | 43/43 | 43/43 |
| Failure-A: pure-utility packages show **no** shipped process/network/dynamic-code evidence | pass | pass |
| Recall sanity: known capabilities detected (e.g. express → network, sharp/esbuild → native) | pass | pass |
| Drift precision: ≤ 2 packages with a tarball-only capability signal | pass (0) | pass (0) |
| Drift coverage: ≥ 85% of GitHub-resolved packages compared | pass (39/42, 93%) | pass (100%) |

- **The 3 Windows misses** (dayjs, nanoid, ws: `github_package_mismatch`) didn't reproduce one package at a time. The suspected cause is a cache race in the concurrent run; it's still being investigated.
- **This isn't a malware detection rate.** It shows the engine doesn't flag benign utilities and does see well-known real capabilities.
- **Reproduce** (needs network and the `semgrep` binary). A dated report is written to `data/benchmarks/`:
  ```bash
  pytest -m live tests/live/test_deps_benchmark.py -v
  ```

### 3.2 Determinism, volume and storage (2026-10-01)

- **Deterministic:** the 7 dependency threats for the demo fixture were identical in every one of 6 runs, unlike the LLM threats. They were `dynamic_code` ×3, `install_hook_present` ×2, `network_environment` ×1, `native_ffi` ×1.
- **Volume:** a 50-package manifest (no LLM, `npm` mode) produced 20 dependency threats. Most for one package: 3. Packages with any: 15 of 50. Largest share for one rule: 18% of packages. The same on a re-run.
- **Time at 50 packages:** 272 s cold and 187 s warm. Both exceed the 180 s default budget, so the web app returns partial results and skips the rest as `time_budget`. That's the designed behaviour; keep demo manifests small.
- **Stored analysis size** (50 rows): median 1 KB, total 332 KB, max 200 KB (`fastify`), next largest 23.7 KB.

### 3.3 Safety checks (2026-10-01)

- **Provenance can't be forged by the LLM.** Across 13 saved models (345 threats: 78 dependency, 137 LLM, 130 rule engine): **0 violations**. Every dependency threat has a known rule and a `package@version` present in that model's scans, and no other threat carries a dependency reference. An adversarial description that told the model to label its threats as dependency findings produced 0 forged rows.
- **No orphaned Semgrep processes.** After the analysis deadline, and after cancelling the task mid-scan, the Semgrep process count fell to 0 within 3 s. Partial results were kept. A real Ctrl+C on Windows wasn't tested directly.

---

## 4. Multiple diagrams

**2026-10-08 · `main` @ `849118a` · fixture + [`examples/arsenal-deps/diagrams/`](../examples/arsenal-deps/diagrams/) (2 Mermaid files + 1 PNG)**

Each demo diagram contains one element found nowhere else: a secrets manager only in the PNG, and a webhook dead-letter queue only in `upload-flow.mmd`. That makes it visible whether the model actually used each diagram.

- **Token cost:** compared with a single-diagram run (`architecture.mmd` only), 3 diagrams added **+4,009 input tokens (+51%)** across the three extraction calls: `summarize` +1,484, `extract_assets` +1,336, `extract_flows` +1,189. That's the 1200×620 PNG plus the second Mermaid file on each call. Threat generation and gap analysis receive no images; the extra Mermaid text added +518 input tokens to the first `generate_threats` call. (Anthropic, n = 1 per arm.)
- **Using image-only content depends on the extraction model** (Anthropic, 1 iteration per run unless noted):

  | Extraction on | Secrets manager (PNG only) | Dead-letter queue (`upload-flow.mmd` only) |
  |---|---|---|
  | Haiku 4.5, run 1 (2 iterations) | not mentioned | ✔ flow + threat |
  | Haiku 4.5, run 2 | only inside flow descriptions, never an asset | ✔ flow |
  | Sonnet 5 (`--step-model extract_assets=main --step-model extract_flows=main`) | ✔ an asset with its own 2 flows | ✔ asset + flow |
  | OpenAI `gpt-4.1` (assets on `gpt-4.1-mini`) | ✔ 2 flows + 1 threat | not mentioned |

  Haiku does read the image but doesn't reliably turn image-only components into assets. Routing extraction to the main model costs about +$0.05 and +16 s per run on this fixture. With 1–2 runs per row, this is indicative only.
- **Upload limits under load:** a 30 MB upload is rejected with 413, and the server's memory rose **+2.8 MB** while handling it (sampled every 20 ms). The bounded read stops at the per-image cap plus one byte. Malformed uploads (6 files, a `.exe`, a non-image renamed `.png`, a truncated PNG) return 422, a viewer token returns 403, and none of them write a row.

**Reproduce:**

```bash
ANTHROPIC_EFFORT=medium paranoid run examples/arsenal-deps/description.md -n 1 \
  -d examples/arsenal-deps/diagrams/architecture.mmd \
  -d examples/arsenal-deps/diagrams/upload-flow.mmd \
  -d examples/arsenal-deps/diagrams/deployment.png \
  --step-model extract_assets=main --step-model extract_flows=main
```

---

## 5. Scoring and enrichment

- **CVSS v3.1** (2026-10-06, Anthropic, one `-n 2` run): in a `cvss` run, all 12 LLM and 7 dependency threats carried valid metric codes, with **0 mismatches** between the stored score and the calculator, and 14 distinct vectors (2.5–9.1). Rule-engine threats get no CVSS score yet. DREAD-only runs use a smaller response schema (2,788 vs 4,689 characters), which saves about 430–670 prompt tokens per `generate_threats` call.
- **ATT&CK/ATLAS mapping coverage** (2026-10-06, one web run): technique matches were saved on 22 of 26 threats (6/10 LLM, 9/9 rule engine, 7/7 dependency). Matching costs ~9 s once per process to embed the catalog, then ~35 ms per threat.
- **ATT&CK/ATLAS precision: provisional.** precision@3 = 0.70 (7/10) on a 10-case golden set, against a 0.6 bar. The expected answers were drafted by Claude and **haven't been reviewed by a human yet**, so don't cite this number until they are. Below the bar, embedding-sourced matches are shown as "suggested". Reproduce with `pytest -m live tests/live/test_attack_mapping_golden.py -v` (needs the embedding model; no API key).

---

## Not measured yet

- **Real-malware recall** for the dependency engine: 10–20 real malicious npm samples, handled as inert data.
- **Repeatable benchmark numbers** with n ≥ 3 for the multiple-diagrams and image-only-component results.
- **Providers other than Anthropic at scale:** OpenAI has one live multi-diagram run; Bedrock, including Opus 5.5 and Fable 5.1, has none.
- **Routing with `--enrich`:** attack-tree and test-case generation on the fast model.
- **Docker image and clean-machine install** timings.
