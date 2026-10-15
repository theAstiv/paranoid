# Benchmarks

Measured cost, time, reliability and output of Paranoid's pipeline, model routing, multi-diagram input and dependency capability engine. Every number on this page carries its date, the models, the sample size and how to reproduce it. If a number isn't here, it hasn't been measured; see [Not measured yet](#not-measured-yet).

## Contents

- [At a glance](#at-a-glance)
- [How these numbers were produced](#how-these-numbers-were-produced)
- [1. Model comparison](#1-model-comparison)
- [2. Model routing](#2-model-routing)
- [3. Multiple diagrams](#3-multiple-diagrams)
- [4. Iterations](#4-iterations)
- [5. Wall time](#5-wall-time)
- [6. Reliability](#6-reliability)
- [7. Dependency capability engine](#7-dependency-capability-engine)
- [8. Scoring and enrichment](#8-scoring-and-enrichment)
- [Not measured yet](#not-measured-yet)
- [Reproducing](#reproducing)

---

## At a glance

| Finding | Number | Where |
|---|---|---|
| Routing extraction to a fast model cuts **those steps'** cost | **−65% to −67%** per step, on both providers measured | [§2](#2-model-routing) |
| Routing's saving on a **whole run** | Not established: ~16% estimated on the direct API, not observed on Bedrock at n = 3 | [§2](#2-model-routing) |
| Haiku 5.5 as the extraction model still reads every diagram | image-only and flow-only components found **3/3** with Haiku 5.5 and Sonnet 5.5 alike | [§3.1](#31-which-extraction-model-reads-the-diagrams) |
| Most reliable main model, 3 benchmark sessions running | **Sonnet 5.5**: 3/3 runs, 34 threats, $0.49/run on Bedrock | [§1](#1-model-comparison) |
| The three demo commands on Sonnet 5.5 (Bedrock) | **141–164 s** median, 15/15 runs clean, $0.41–$0.56 per run | [§5.1](#51-demo-commands-on-bedrock-bm10-demo) |
| Models reliable on the full fixture (3/3 runs) | **8 of 11**; models producing any LLM output went from 4 of 10 (10-09) to 9 of 11 | [§6.2](#62-structured-output-reliability-across-sessions) |
| 5 iterations instead of 3 (same model and inputs) | **+6 threats (+17%)** for **+81% cost** | [§4](#4-iterations) |
| Dependency threats on the fixture | **7, identical** in every run | [§7.2](#72-determinism-volume-and-storage-2026-10-01) |
| LLM forging a dependency finding | **0** of 345 threats, including an adversarial prompt | [§7.3](#73-safety-checks-2026-10-01) |
| Real malicious npm packages flagged (static, no LLM) | **12/20**: compromised releases **9/14**, malicious-intent packages **3/6**; every hit through install-time behaviour, every miss named. Not "catches supply-chain attacks" | [§7.4](#74-real-malware-recall-2026-10-15) |

---

## How these numbers were produced

### Two measurement periods

| Period | Provider | How | Models |
|---|---|---|---|
| 2026-09-26 → 10-08 | Direct Anthropic API, plus one OpenAI run | Hand-run CLI and web sessions, scratch databases | `claude-sonnet-5` main, `claude-haiku-4-5-20251001` fast; OpenAI `gpt-4.1` / `gpt-4.1-mini` |
| 2026-10-09 → 10-12 | AWS Bedrock (`us-east-2`) | The benchmark harness in [`tests/bench/`](../tests/bench/README.md), 3 sessions, 88 pipeline runs in the latest result set | Opus 5.5, Fable 5.1, Sonnet 5.5, Sonnet 5, Haiku 5.5, Haiku 4.5, GPT-OSS 120B / 20B, Qwen, DeepSeek; OpenAI `gpt-4.1` direct |

Numbers from the two periods **aren't directly comparable**. Bedrock has no prompt caching in Paranoid's provider (cache reads are a large discount on the direct API), and the model generations differ.

### The fixture

Unless stated otherwise, everything runs on [`examples/arsenal-deps/`](../examples/arsenal-deps/): "MediaDrop", a fictional image-upload and webhook service.

- `description.md`, with its assumptions section.
- 8 real npm dependencies in `package.json` and `package-lock.json`.
- Three diagrams of the same system. Each has one element that appears **nowhere else**, which shows whether a model actually used that diagram:
  - `deployment.png`: a **secrets manager**;
  - `upload-flow.mmd`: a webhook retry / **dead-letter queue** branch;
  - `architecture.mmd`: the component view with trust boundaries.

Results on other systems will differ. One fixture is a demo-sized system, not a benchmark suite of applications.

### Settings

- **Effort:** Claude models ran at `ANTHROPIC_EFFORT=medium` (on Bedrock since #129).
- **Scoring:** `--scoring-method both` (DREAD and CVSS) unless stated.
- **Routing:** "main" runs `summarize`, `generate_threats` and `gap_analysis`. "Fast" may run `extract_assets`, `extract_flows`, attack trees and test cases. `generate_threats` and `gap_analysis` never run on the fast model.

### Statistics and costs

- Numbers are **median [min–max] (n)**. n < 3 is **indicative only**.
- **Cost is modelled, not billed:** recorded token counts × each provider's on-demand price per million tokens, read from the provider's pricing page on the date of the run. Bedrock rows use `us-east-2` prices.
- **Whole-run cost differences at n = 3 are noise.** Whole-run cost varied ±17% within a single arm. Comparisons are made per pipeline step, where a step's model is the only thing that changed.
- **A "fallback"** is a run where the LLM produced no threats and the pipeline completed on the rule engine alone. On the fixture that's **17 threats (10 rule-engine + 7 dependency)**. Every harness arm with a model has a gate that fails a run with zero LLM threats. A run total of 17 isn't proof of a fallback by itself: LLM threats can deduplicate against rule-engine ones.
- **Quantity isn't quality.** Threat counts below are counts. Quality scoring against the reviewed MediaDrop reference checklist hasn't been run yet ([Not measured yet](#not-measured-yet)).

---

## 1. Model comparison

**2026-10-12 · `main` @ `d457f67` (includes #138) · AWS Bedrock · `mc` suite, n = 3 per model**

Each model ran as **both** main and fast, on the full fixture: description, 3 diagrams (text-only models get the two Mermaid files, not the PNG), manifest and lockfile, dependency mode `both`, `-n 2`.

| Model | Runs ok | Threats | Cost/run | Wall time | Notes |
|---|---:|---:|---:|---:|---|
| Opus 5.5 | 3/3 | 38 [36–39] | $0.76 | 689 s | most threats |
| Sonnet 5.5 | 3/3 | 34 [34–42] | $0.49 | 330 s | most reliable across all 3 sessions |
| Haiku 4.5 | 3/3 | 34 [17–35] | $0.15 | 219 s | |
| Sonnet 5 | 3/3 | 30 [28–31] | $0.26 | 211 s | 0/3 before #138 |
| DeepSeek | 3/3 | 30 [29–32] | $0.055 | 393 s | 1/3 before #138 |
| Fable 5.1 | 3/3 | 28 [17–34] | $3.32 | 759 s | 2 fallbacks recorded (detail not in the session report) |
| Qwen | 3/3 | 27 [27–28] | $0.012 | 119 s | |
| Haiku 5.5 | 3/3 | 17 [17–26] | $0.045 | 98 s | low yield as the only model; see §3.1 for it as the fast model |
| GPT-OSS 120B | 0/3 | — | $0.016 | 137 s | unsupported: wrong field names ([§6.3](#63-what-still-fails)) |
| GPT-OSS 20B | 0/3 | 0–26 | $0.020 | 192 s | unsupported: wrong field names, flat CVSS ([§6.3](#63-what-still-fails)) |
| OpenAI `gpt-4.1` (direct) | not run | — | — | — | the bench machine's API key was rejected |

**Reading the table:**
- **Sonnet 5.5** is the recommended main model: 3/3 runs in all three sessions, the second-highest yield, and a third of Opus 5.5's wall time.
- **More threats isn't automatically better.** Until quality scoring has run, Opus 5.5's 38 and Sonnet 5.5's 34 aren't evidence that one model finds *better* threats.
- **The minimum of 17** for Haiku 4.5, Haiku 5.5 and Fable 5.1 equals the rule-engine baseline. Those runs passed the "LLM produced output" gate, so they contain LLM threats, but few of them.

---

## 2. Model routing

The claim this section backs: **routing the two extraction steps to a cheaper model cuts those steps' cost by about two-thirds.** The per-run saving depends on the provider and is smaller than that.

### 2.1 AWS Bedrock (2026-10-12)

**`main` @ `d457f67` · Sonnet 5.5 main, Haiku 5.5 fast · description + manifest, no diagrams, dependency mode `npm`, `-n 3` · `bm2-routing`, n = 3 per arm**

| Step | Routing off | Routing on | Cost change | Time off | Time on |
|---|---:|---:|---:|---:|---:|
| `extract_assets` | $0.0193 | $0.0066 | **−66%** | 9.2 s | 11.9 s |
| `extract_flows` | $0.0396 | $0.0132 | **−67%** | 16.7 s | 14.5 s |
| `summarize` | $0.0051 | $0.0052 | +1% | 1.7 s | 1.7 s |
| `generate_threats` | $0.1457 | $0.1740 | +19% | 64.9 s | 68.3 s |
| `gap_analysis` | $0.0663 | $0.0915 | +38% | 22.4 s | 34.5 s |
| **Whole run** | **$0.290** · 147 s · 35 threats | **$0.317** · 166 s · 35 threats | | | |

- The routed steps are the only ones whose model changed. Their −66% / −67% is the finding.
- `generate_threats` and `gap_analysis` always run on the main model. Their increases are run-to-run variation, which is also why the routed run came out slightly *more* expensive overall.
- **On Bedrock, a whole-run saving wasn't observed at n = 3.** The extraction steps are about a fifth of a run's cost here, and Bedrock has no prompt-cache discount to shift that share.

### 2.2 Direct Anthropic API (2026-10-05)

**`main` @ `d0f0994` · `claude-sonnet-5` main, `claude-haiku-4-5-20251001` fast · n = 3 per arm**

| Routed step | Sonnet 5 (3 runs) | Haiku 4.5 (3 runs) | Cost | Median duration per run |
|---|---|---|---|---|
| `extract_assets` | $0.0608 | $0.0238 | −61% | 14.0 s → 10.6 s |
| `extract_flows` | $0.1721 | $0.0570 | −67% | 34.2 s → 23.8 s |
| **Both** | **$0.2328** | **$0.0808** | **−65%** | **47.8 s → 34.2 s (−28%)** |

- Those two steps were about 25% of a run's cost without `--enrich`, which *models* a saving of about 16% per run. It isn't an observed whole-run difference: the measured whole-run gap (0.58%) was inside the ±17% spread within one arm.
- Haiku extracted more flows (17/16/18 → 22/23/21) and gave credential handling its own flows more often (5/4/5 → 10/11/7). Whether that changes threat quality wasn't assessed.
- One pre-flight gap-check call per run (about 4–6% of run cost) wasn't counted in either arm; it's counted since #116.

### 2.3 Routing with `--enrich`

`bm3-enrich-routing` (Bedrock, 2026-10-11, n = 2 per arm) passed all its gates: every threat got an attack tree and a test suite with routing on and off. Its per-step comparison wasn't part of the session report, so there's no number for the enrichment steps yet.

---

## 3. Multiple diagrams

### 3.1 Which extraction model reads the diagrams

**2026-10-12 · `main` @ `d457f67` · Bedrock · 3 diagrams, `-n 1` · `bm4-diagrams`, n = 3 per arm**

| Extraction on | Cost/run | Wall time | Threats | Secrets manager (PNG only) | Dead-letter queue (`upload-flow.mmd` only) |
|---|---:|---:|---:|---|---|
| Haiku 5.5 (fast) | $0.106 | 65 s | 19 [18–20] | **3/3** | **3/3** |
| Sonnet 5.5 (main) | $0.144 | 65 s | 19 [19–19] | 3/3 | 3/3 |

- Per step, Haiku 5.5 was 66% cheaper on `extract_assets` ($0.0068 vs $0.0204) and 69% cheaper on `extract_flows` ($0.0125 vs $0.0399).
- **This reverses the earlier Haiku 4.5 result.** On 10-08, Haiku 4.5 never turned the PNG-only secrets manager into an asset (0/2, table below). With Haiku 5.5 as the fast model, routing extraction back to the main model for image input isn't needed.

**Earlier, direct API (2026-10-08, n = 1–2 per row, indicative):**

| Extraction on | Secrets manager (PNG only) | Dead-letter queue (`upload-flow.mmd` only) |
|---|---|---|
| Haiku 4.5, run 1 (2 iterations) | not mentioned | ✔ flow + threat |
| Haiku 4.5, run 2 | only inside flow descriptions, never an asset | ✔ flow |
| Sonnet 5 (`--step-model extract_assets=main --step-model extract_flows=main`) | ✔ an asset with its own 2 flows | ✔ asset + flow |
| OpenAI `gpt-4.1` (assets on `gpt-4.1-mini`) | ✔ 2 flows + 1 threat | not mentioned |

### 3.2 Token cost of extra diagrams

**2026-10-08 · `main` @ `849118a` · direct Anthropic · n = 1 per arm**

- Compared with a single-diagram run (`architecture.mmd` only), 3 diagrams added **+4,009 input tokens (+51%)** across the three extraction calls: `summarize` +1,484, `extract_assets` +1,336, `extract_flows` +1,189. That's the 1200×620 PNG plus the second Mermaid file on each call.
- Threat generation and gap analysis receive no images. The extra Mermaid text added +518 input tokens to the first `generate_threats` call.

### 3.3 Upload limits under load (2026-10-08)

- A 30 MB upload is rejected with 413, and the server's memory rose **+2.8 MB** while handling it (sampled every 20 ms). The bounded read stops at the per-image cap plus one byte.
- Malformed uploads (6 files, a `.exe`, a non-image renamed `.png`, a truncated PNG) return 422. A viewer token returns 403. None of them write a row.

---

## 4. Iterations

**2026-10-12 · `main` @ `d457f67` · Bedrock · Sonnet 5.5, no fast model · description + manifest, no diagrams, dependency mode `npm` · n = 3 per arm**

Both arms use the same model and inputs. Only the iteration count differs, and `MIN_ITERATIONS=5` forces all five in the second arm (the first may stop early once gap analysis is satisfied).

| Arm | Threats | LLM / rule engine / dependency | Cost/run | Wall time |
|---|---:|---|---:|---:|
| `-n 3` (`bm2-routing`, routing off) | 35 | — | $0.290 | 147 s |
| `-n 5`, forced (`bm5-iterations`) | 41 [39–41] | 25 / 9 / 7 | $0.526 | 223 s |

- Two more iterations added **+6 threats (+17%)** for **+81% cost** and +52% wall time.
- The report gives totals, not per-iteration counts, so where the curve flattens isn't pinned down yet. On this fixture, 2–3 iterations is the cost-effective setting.

---

## 5. Wall time

### 5.1 Demo commands on Bedrock (`bm10-demo`)

**2026-10-12 · `main` @ `f8d904b` · Sonnet 5.5 main, Haiku 5.5 fast · n = 5 per command · 15 of 15 runs ok**

| Command | Median [min–max] | Cost/run | Threats | LLM / rule engine / dependency | Diagram probes |
|---|---:|---:|---:|---|---|
| Scenario 1: dependencies, deep mode, `-n 2` | 164 s [140–166] | $0.412 | 34 [30–37] | 18 / 9 / 7 | — (no diagrams) |
| Scenario 2: 3 diagrams, extraction on main, `-n 2` | 160 s [155–173] | $0.562 | 37 [34–38] | 21 / 9 / 7 | secrets manager 5/5, dead-letter queue 5/5 |
| Scenario 3: routing + SARIF, `-n 2` | 141 s [135–154] | $0.425 | 34 [32–40] | 18 / 9 / 7 | — (no diagrams) |

- **No retries and no fallbacks** in any run: 0 non-JSON retries, 0 token-budget bumps, 0 rule-engine fallbacks, 0 refusals, 0 timeouts.
- **One expected switch per run:** Sonnet 5.5 rejects forced tool choice, so each run switches to `auto` tool choice once at its first structured call (#124). This shows as `forced_tool_fallback` 5/5 in the raw report. It's the designed behaviour, not a failure.
- Total: $7.09 for the 15 runs.
- **Harness note:** `bm10-demo` is defined on the Opus 5.5 slot. This run overrode that slot's model ID with `us.anthropic.claude-sonnet-5-5`, so raw results are labelled `OPUS_55` with the Sonnet 5.5 `model_id`.

**For comparison, Opus 5.5 main** (2026-10-11, **before #138**, same commands, n = 5):

| Command | Opus 5.5 median / p90 / cost / threats | Sonnet 5.5 vs Opus 5.5: time | cost |
|---|---|---:|---:|
| Scenario 1 | 477 s / 780 s / $0.75 / 35 | −66% | −45% |
| Scenario 2 | 347 s / 476 s / $0.47 / 17 | −54% | +20% |
| Scenario 3 | 486 s / 943 s / $0.75 / 35 | −71% | −43% |

- On the demo commands, Sonnet 5.5 was **2.2–3.4× faster** than Opus 5.5, with a far tighter spread (slowest Sonnet run 173 s; Opus p90 up to 943 s).
- **Scenario 2's comparison is confounded.** Several Opus runs fell back to the rule engine (a median of 17 threats is the fallback signature), and the structured-output failures behind such fallbacks were fixed by #138, between the two runs. Part of Sonnet's +20% cost is paying for LLM output that Opus's fallback runs didn't produce.
- These are counts and timings, not a quality comparison.

### 5.2 Direct Anthropic API (2026-10-01)

**`claude-sonnet-5`, effort `medium` · STRIDE · n = 1 per row**

| Run | Path | Dependency cache | Mode | Dependency analysis | Total | Iterations | Threats (LLM / rules / deps) |
|---|---|---|---|---|---|---|---|
| B1 | API | cold | `npm` | 29.2 s | 169 s | 2 | 28 (11 / 10 / 7) |
| B2 | API | warm | `npm` | 25.9 s | 146 s | 1 | 27 (10 / 10 / 7) |
| B3 | API | cold | `both` | 61.6 s | 296 s | 3 | 35 (18 / 10 / 7) |
| B4 | API | warm | `both` | 51.2 s | 200 s | 1 | 27 (10 / 10 / 7) |
| B8 | API | — | no manifest | — | 244 s | 3 | 26 (16 / 10 / 0) |

- **The dependency cache barely helps:** warm vs cold saves 4–10 s, because Semgrep scanning dominates, not the download. A pre-warmed cache matters for offline use, not speed.
- **Deep mode** (`--deps-source both`) adds about 30 s for 8 packages, well inside the default 180 s budget.
- **Effort matters most:** a full run took 169 s at `ANTHROPIC_EFFORT=medium` against 517 s at the default effort.

### 5.3 Flagship full-input sessions (`bm13-flagship`)

**Bedrock · full fixture + `--enrich`, `-n 3`, every step on the flagship model · n = 1 per model**

| Model | Date | Wall time | Cost | Threats (LLM / rules / deps) | Refusals logged |
|---|---|---:|---:|---|---:|
| Opus 5.5 | 2026-10-12 | 1,961 s | $0.87 | 37 (21 / 9 / 7) | 42 |
| Fable 5.1 | 2026-10-11 | 2,799 s | $4.29 | 37 (21 / 9 / 7) | 106 |

- Both runs completed, with every threat enriched.
- **Refusals** are calls the model's safety filtering declined. They're counted separately since #128, and the run continues on the remaining calls. Which pipeline step they come from hasn't been broken down yet.

---

## 6. Reliability

### 6.1 Harness gates (2026-10-12)

**Latest result per arm · 35 of 43 arms pass · all 8 failing arms are GPT-OSS (6) or OpenAI direct (2)**

| Suite | What it checks | Arms | Status |
|---|---|---:|---|
| `e2e-cli` | Full input per model; SARIF, Markdown, PDF and JSON exports valid; CVSS consistent; exactly 7 dependency threats | 11 | 8 pass; GPT-OSS ×2 and OpenAI direct fail |
| `e2e-web` | Server + API: uploads, SSE, diagram routes, exports, re-runs | 2 | Opus 5.5 passes; GPT-OSS fails |
| `e2e-enrich` | An attack tree and a test suite for every threat | 3 | 2 pass; GPT-OSS fails |
| `e2e-maestro` | STRIDE + MAESTRO on the RAG chatbot example; MAESTRO categories saved | 1 | pass (failed on 10-09, before #137) |
| `e2e-degraded` | No reachable provider; dependency deadline; text-only model with a PNG | 3 | 2 pass; the GPT-OSS text-only arm fails |
| `mc` | See [§1](#1-model-comparison) | 11 | 8 at 3/3; GPT-OSS ×2 and OpenAI direct fail |
| `bm2`, `bm3`, `bm4`, `bm5`, `bm10`, `bm13` | See §2–§5 | 12 | all pass |

### 6.2 Structured-output reliability across sessions

Every non-environment failure in these sessions had the same effect: a model returned structured output the schema rejected, the step failed, and the run fell back to the rule engine.

| | 2026-10-09 | 2026-10-11 | 2026-10-12 |
|---|---:|---:|---:|
| Models producing LLM output in at least one `mc` run | 4 of 10 | 6 of 11 | **9 of 11** |
| Models at 3/3 in `mc` | — | 6 of 11 | **8 of 11** |

What fixed each failure shape:

| Shape | Seen on | Fixed by |
|---|---|---|
| Rejects forced tool choice | Opus 5.5, Fable 5.1 | #124 |
| Image sent to a text-only model | GPT-OSS, Qwen, DeepSeek | #128 |
| A list field returned as a JSON string; an empty tool input | Claude 5.x | #130 |
| The whole response JSON-encoded into one field; malformed JSON | Sonnet 5, Haiku 5.5 | #136 |
| `cvss` left out when optional | Opus 5.5 | #137 (required when CVSS is requested) |
| Response nested under an extra key (`input`, `data`) | Sonnet 5, DeepSeek | #138 |
| A value outside the schema (CVSS `AC:M`, a CVSS v2 value) | DeepSeek | #138 retries with the exact field and allowed values; the value is never accepted |

#138 also gave the direct Anthropic provider the same recovery. The ~2-in-10 "non-JSON response" flake seen on direct-API runs before it (10-01 → 10-08) hasn't been re-measured since.

### 6.3 What still fails

- **GPT-OSS 120B and 20B: schema adherence.** Re-run on 2026-10-12 at `main` @ `f8d904b` (after #138), 13 runs across `e2e-cli`, `e2e-web`, `e2e-enrich`, `e2e-degraded` and `mc`: **13 of 13 failed**, at $0.010–$0.020 per run.
  - **Fixed by earlier PRs:** no run answered in prose instead of calling the tool (#138), and no run was sent an image it couldn't take (#128).
  - **What remains:** the models call the tool but fill it in wrong. They write field names in PascalCase (`Type`, `Name`, `Description` instead of `type`, `name`, `description`) and send CVSS as a flat abbreviated object (`{'av': 'N', 'ac': 'L', …}`) instead of the nested metrics. The validation retry, which names the failing fields, doesn't get them to correct it within 3 attempts.
  - Paranoid treats the GPT-OSS models as **unsupported** for structured output. Fixing them would mean rewriting keys the models got wrong, which isn't planned.
- **OpenAI direct:** not measured this period (credential problem on the bench machine, not a product failure).

---

## 7. Dependency capability engine

### 7.1 Benchmark gates (43 popular npm packages)

**2026-09-26 · Windows and Linux · each package at its `latest` tag on that date. Re-run on 2026-10-12 on macOS: all gates passed.**

| Gate | Windows | Linux |
|---|---|---|
| Packages scanned | 43/43 | 43/43 |
| Failure-A: pure-utility packages show **no** shipped process/network/dynamic-code evidence | pass | pass |
| Recall sanity: known capabilities detected (e.g. express → network, sharp/esbuild → native) | pass | pass |
| Drift precision: ≤ 2 packages with a tarball-only capability signal | pass (0) | pass (0) |
| Drift coverage: ≥ 85% of GitHub-resolved packages compared | pass (39/42, 93%) | pass (100%) |

- **The 3 Windows misses** (dayjs, nanoid, ws: `github_package_mismatch`) didn't reproduce one package at a time. The suspected cause is a cache race in the concurrent run.
- **This isn't a malware detection rate.** It shows the engine doesn't flag benign utilities and does see well-known real capabilities. For real malware see [§7.4](#74-real-malware-recall-2026-10-15).

### 7.2 Determinism, volume and storage (2026-10-01)

- **Deterministic:** the 7 dependency threats for the fixture were identical in every one of 6 runs, unlike the LLM threats: `dynamic_code` ×3, `install_hook_present` ×2, `network_environment` ×1, `native_ffi` ×1. On Bedrock (10-12), the `e2e-cli` gate "exactly 7 dependency threats" passed for every model that produced LLM output, and the iteration and flagship runs also report 7.
- **Volume:** a 50-package manifest (no LLM, `npm` mode) produced 20 dependency threats. Most for one package: 3. Packages with any: 15 of 50. Largest share for one rule: 18% of packages. The same on a re-run.
- **Time at 50 packages:** 272 s cold and 187 s warm. Both exceed the 180 s default budget, so the web app returns partial results and skips the rest as `time_budget`. That's the designed behaviour; keep demo manifests small.
- **Stored analysis size** (50 rows): median 1 KB, total 332 KB, max 200 KB (`fastify`), next largest 23.7 KB.

### 7.3 Safety checks (2026-10-01)

- **Provenance can't be forged by the LLM.** Across 13 saved models (345 threats: 78 dependency, 137 LLM, 130 rule engine): **0 violations**. Every dependency threat has a known rule and a `package@version` present in that model's scans, and no other threat carries a dependency reference. An adversarial description that told the model to label its threats as dependency findings produced 0 forged rows.
- **No orphaned Semgrep processes.** After the analysis deadline, and after cancelling the task mid-scan, the Semgrep process count fell to 0 within 3 s. Partial results were kept. A real Ctrl+C on Windows wasn't tested directly.

### 7.4 Real-malware recall (2026-10-15)

**2026-10-15 · Linux (WSL Ubuntu 24.04) · Semgrep 1.178.0 · engine defaults · dependency engine as on `main` @ `3725ed8` · n = 20 · no LLM.**

20 real malicious npm packages from the DataDog [`malicious-software-packages-dataset`](https://github.com/DataDog/malicious-software-packages-dataset) @ `6ff638a`, listed with hashes in [`tests/bench/fixtures/bm1-samples.json`](../tests/bench/fixtures/bm1-samples.json):

- **14 compromised releases of real packages**, hand-picked famous incidents across 9 campaigns, at most 3 per campaign.
- **6 malicious-intent packages** (published to deliver malware), drawn at random with a fixed seed from the 12,847 in the dataset, so not cherry-picked.

The samples are handled as inert files: never installed or run. Each is decrypted into a scratch folder, scanned as the npm tarball and deleted again. For a compromised release the engine also compares it with its GitHub source (drift) and with the previous clean release (delta). That clean release is scanned as a **control**: a static finding or drift signal only counts when the clean release doesn't have it too. Malicious-intent packages have no clean release, so any finding counts.

| Group | Flagged |
|---|---|
| Compromised releases | **9/14** |
| Malicious-intent packages | **3/6** |
| All | **12/20** |

| Campaign (compromised releases) | Flagged |
|---|---|
| 2025-09 Shai-Hulud worm (`@ctrl/tinycolor`, `koa2-swagger-ui`, `@crowdstrike/commitlint`) | 3/3 |
| 2025-07 maintainer phish, install-script loader (`eslint-config-prettier`, `synckit`) | 2/2 |
| 2024-12 stolen tokens, postinstall miner (`@rspack/core`, `vant`) | 2/2 |
| 2025-08 s1ngularity (`@nx/devkit`) | 1/1 |
| 2025-07 `is` | 1/1 |
| 2025-09 maintainer phish, browser crypto clipper (`debug`, `@duckdb/node-api`) | 0/2 |
| 2025-04 `xrpl` backdoor | 0/1 |
| 2024-12 `@solana/web3.js` backdoor | 0/1 |
| 2026-05 `node-ipc` | 0/1 |

- **Every hit came through install-time behaviour.** All 12 flagged samples have an install hook. Among the 9 compromised hits, delta flagged all 9 (`install_hook_added`, plus `suspicious_capability_addition` on 4), drift flagged 7, and 8 had a static finding their clean release lacks.
- **Every miss is a payload in the package's own code, with no install hook:**

| Missed | Why |
|---|---|
| `debug@4.4.2`, `@duckdb/node-api@1.3.3` | Obfuscated browser code injected into a file that also exists in the repo (`debug`'s `src/index.js` grew from 314 B to 76.7 KB). No capability rule matches it, and drift only checks such a file for new capability evidence, not for a change in size or content |
| `xrpl@4.2.1`, `@solana/web3.js@1.95.7`, `node-ipc@12.0.1` | Key or data exfiltration through `network` code the clean release already had, so delta shows nothing new; `network` alone raises no finding |
| `maya-nasicampur61-breki`, `dian-tapai59-sluey` (malicious-intent) | Placeholder Next.js projects: `filesystem` and `process` only, which raise no finding on their own |
| `hayase-extensions` (malicious-intent) | `network` only |

- **False-alarm baseline:** 6 of the 14 clean previous releases already have a static finding, and 1 of 13 shows a drift signal against its own GitHub source. Without the control the compromised-release number would look better than it is.
- **Drift needs a GitHub ref, and attackers rarely push one.** Only 2 of the 14 malicious versions resolved to a ref of their own; the others fell back to the clean release's ref. Drift ran for 11 of 14. For 3 it didn't: `@nx/devkit`'s repo tarball exceeds the 50 MB download cap, `eslint-config-prettier` isn't found inside its repo at that commit, and `@duckdb/node-api` resolved no GitHub source.
- **`@duckdb/node-api`'s control is a prerelease** (`1.3.2-alpha.26`), because the package has never published a stable release before 1.3.3.

**Caveats:** n = 20, so each sample moves its group by 7 (compromised) or 17 (malicious-intent) points. The dataset was found mostly by GuardDog, a Semgrep-based tool, which biases it towards what this kind of scanner can see. The best-known older incidents (event-stream, ua-parser-js, coa, rc) aren't in it. This is static analysis only; payloads fetched at runtime are out of scope. Quote it as **k/N with the misses named**, never as "catches supply-chain attacks".

---

## 8. Scoring and enrichment

- **CVSS v3.1:**
  - 2026-10-06, direct Anthropic, one `-n 2` run: in a `cvss` run, all 12 LLM and 7 dependency threats carried valid metric codes, with **0 mismatches** between the stored score and the calculator, and 14 distinct vectors (2.5–9.1).
  - Since #137, CVSS is a required field whenever it's requested, so an LLM can't skip it. Rule-engine threats get a deterministic default vector (#132).
  - On Bedrock (2026-10-12), the CVSS consistency gate (every vector parses and matches its stored score) passed in all 9 passing `e2e-cli` and `e2e-web` arms, including Opus 5.5 on the web path, which failed it on 10-09.
  - DREAD-only runs use a smaller response schema (2,788 vs 4,689 characters), which saves about 430–670 prompt tokens per `generate_threats` call.
- **ATT&CK/ATLAS mapping coverage** (2026-10-06, one web run): technique matches were saved on 22 of 26 threats (6/10 LLM, 9/9 rule engine, 7/7 dependency). Matching costs ~9 s once per process to embed the catalog, then ~35 ms per threat.
- **ATT&CK/ATLAS precision: provisional.**
  - precision@3 = 0.70 (7/10) on a 10-case golden set, against a 0.6 bar; the 2026-10-12 re-run passed the same bar.
  - The expected answers were drafted by Claude and **haven't been reviewed by a human yet**, so don't cite this number until they are.
  - Below the bar, embedding-sourced matches are shown as "suggested".

---

## Not measured yet

- **Threat quality:** model output against the 18-threat MediaDrop reference checklist. The checklist and its match threshold still need human review.
- **OpenAI direct** at n ≥ 3 (BM12 parity).
- **Code as input** (`e2e-code`): needs the context-link binary on the bench machine.
- **Per-iteration yield** (where the curve flattens) and **per-step routing with `--enrich`**.
- **Prompt caching on Bedrock:** not implemented, so Bedrock costs here are without it.
- **Docker image and clean-machine install** timings.

---

## Reproducing

**Bedrock benchmarks** (§1–§6): see [`tests/bench/README.md`](../tests/bench/README.md) for setup, the price file and the spend cap. Always print the cost estimate first:

```bash
python -m tests.bench plan mc bm2-routing bm4-diagrams bm5-iterations
python -m tests.bench run mc --yes --max-cost 20
python -m tests.bench report mc
```

**Direct-API routing** (§2.2), OFF arm shown; the ON arm drops `FAST_MODEL=""`. Per-step usage is in `threat_models.usage_summary` in the scratch DB:

```bash
DB_PATH=./data/routing-measure.db ANTHROPIC_EFFORT=medium FAST_MODEL="" \
  paranoid run examples/arsenal-deps/description.md \
  --manifest examples/arsenal-deps/package.json \
  --lockfile examples/arsenal-deps/package-lock.json \
  --deps-source npm -n 3 --format full -o off-1.json
```

**Multiple diagrams** (§3):

```bash
ANTHROPIC_EFFORT=medium paranoid run examples/arsenal-deps/description.md -n 1 \
  -d examples/arsenal-deps/diagrams/architecture.mmd \
  -d examples/arsenal-deps/diagrams/upload-flow.mmd \
  -d examples/arsenal-deps/diagrams/deployment.png
```

**No-LLM suites** (§7.1, §8; network and `semgrep` for the first, the embedding model for the second):

```bash
pytest -m live tests/live/test_deps_benchmark.py -v
pytest -m live tests/live/test_attack_mapping_golden.py -v
```

**Real-malware recall** (§7.4; Linux or WSL with the samples in the Linux filesystem, `semgrep` and network). The fetch keeps the dataset's encrypted zips and refuses a folder inside the repo; the run decrypts one sample at a time into the scratch folder and deletes it afterwards. Details and handling rules: [`tests/bench/README.md`](../tests/bench/README.md) §7.

```bash
python scripts/fetch_bm1_samples.py ~/bench-malware
python -m tests.bench.malware --dir ~/bench-malware --scratch ~/bench-scratch
```
