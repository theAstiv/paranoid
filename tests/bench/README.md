# Live E2E and benchmark harness

This directory runs Paranoid's full pipeline against real models, mostly on **AWS Bedrock**, and records two kinds of result:

- **E2E gates:** pass/fail checks that every feature works end to end on every model in scope.
- **Benchmarks:** measured cost, time, reliability and threat-model quality, with the date, commit, models and sample size attached to every number.

It isn't part of CI and isn't shipped in the wheel. It's driven by `python -m tests.bench …` and configured entirely by environment variables.

> **If you're an agent picking this up on a new machine, read this whole file before running anything.** Two rules are absolute:
> 1. **Never start a billed run without the user's approval of the cost estimate** that `python -m tests.bench plan` prints. Post the estimate, wait for a yes, then run.
> 2. **Never commit** `tests/bench/bench.env`, `tests/bench/prices.json`, anything under `data/`, or any malware sample. They're gitignored; keep it that way.

---

## 1. What's being tested and why

The pipeline takes a system description plus optional inputs (architecture diagrams, a `package.json`/lockfile for the dependency capability engine, a code repo via context-link). It runs extraction (`summarize`, `extract_assets`, `extract_flows`), then iterative threat generation and gap analysis, then the rule engine, dependency threats, ATT&CK/ATLAS technique mapping and CVSS/DREAD scoring, with optional `--enrich` (attack trees + Gherkin test cases).

The fixture for almost everything is **`examples/arsenal-deps/`**: "MediaDrop", a fictional image-upload service.
- **Description:** `description.md`, which includes its assumptions section.
- **Dependencies:** 8 direct npm dependencies, in `package.json` and `package-lock.json`.
- **Diagrams** in `diagrams/`: `architecture.mmd`, `upload-flow.mmd` and `deployment.png`. Each diagram has one element that appears **nowhere else**:
  - a **secrets manager**, only in `deployment.png`;
  - a webhook **retry / dead-letter queue** branch, only in `upload-flow.mmd`.

  Whether those reach the extracted assets, flows and threats shows whether the model actually used each diagram.

Model routing: each extraction step can run on a cheaper "fast" model, while `generate_threats` and `gap_analysis` always run on the "main" model.

### Results already on record (direct Anthropic API, before this harness)

Use these as sanity baselines, not as the answer:

| What | Result | n |
|---|---|---|
| Routing extraction Sonnet 5 → Haiku 4.5 (2026-10-05) | Those two steps: cost −65%, latency −28%; about −16% of a run's cost | 3 per arm |
| Full run, 8-package fixture, effort `medium` (2026-10-01) | 146–296 s; a warm dependency cache saves only 4–10 s | 1 per row |
| Dependency threats on the fixture | Always exactly **7** | 6 of 6 runs |
| 3 diagrams vs 1 (2026-10-08) | +4,009 input tokens (+51%) across the 3 extraction calls | 1 per arm |
| PNG-only secrets manager reaching the model (2026-10-08) | Sonnet extraction: became an asset; Haiku extraction: never an asset (0/2); `gpt-4.1`: in 2 flows | 1–2 per row |
| Non-JSON response flake ("P1") | ~2 in 10 runs, recovered by a retry; seen on `gap_analysis` and once on `generate_threats` | — |

---

## 2. Setup

```bash
pip install -e ".[dev,bedrock]"   # bedrock extra = boto3; dev includes pypdf for the PDF export gate
pip install semgrep               # external binary used by the dependency engine
```

Then check:

```bash
python -m tests.bench list
```

- **Optional:** the context-link binary (`bin/context-link` or `CONTEXT_LINK_BINARY`), for the code-as-input suites.
- **Optional:** Node.js, for parsing attack-tree Mermaid in the enrich-quality checks.

**Configuration:** copy `tests/bench/bench.env.example` to `tests/bench/bench.env` and fill in what you have. Real environment variables override the file, so a one-off override needs no edit. Copy `tests/bench/prices.example.json` to `tests/bench/prices.json` and fill in prices (see §4).

| Variable | Meaning |
|---|---|
| `AWS_REGION`, `AWS_PROFILE` | Bedrock. Or the standard `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` in the shell. Never written to any artifact |
| `OPENAI_API_KEY` | Direct OpenAI (the light `OPENAI_DIRECT` arm). Also read from the repo's `.env` |
| `BENCH_MODEL_<SLOT>` | The Bedrock model ID or inference profile for each slot: `OPUS_55`, `FABLE_51`, `SONNET_55`, `SONNET_5`, `HAIKU_55`, `HAIKU_45`, `GPT_OSS_120B`, `GPT_OSS_20B`, `QWEN`, `DEEPSEEK`. `BENCH_MODEL_OPENAI_DIRECT` defaults to `gpt-4.1`. **An empty slot is skipped, and the skip is reported** |
| `BENCH_IMAGES_<SLOT>` | `true`/`false`: whether a slot is sent images. Defaults: Claude and OpenAI direct `true`; gpt-oss, Qwen and DeepSeek `false`. Set from the spike results |
| `BENCH_ROUTING_MAIN`, `BENCH_ROUTING_FAST` | Slot *names* for the routing benchmarks (e.g. `OPUS_55` / `HAIKU_55`) |
| `BENCH_PRICES_FILE` | Price table (§4) |
| `BENCH_MAX_COST_USD` | Hard spend cap for one `run` invocation. **Required** for `run` |
| `BENCH_EFFORT` | Effort for Claude runs (default `medium`). Today this only reaches the *direct* Anthropic provider, not Bedrock (§6) |
| `BENCH_RUN_TIMEOUT_S` | Per-run wall-clock limit (default 1800 s; enrich/web/flagship arms multiply it) |
| `BENCH_CODE_REPO` | A small local git repo for code-as-input; those arms are skipped when unset |
| `BENCH_MALWARE_DIR` | Inert malicious npm tarballs for the recall benchmark (§7); skipped when unset |
| `BENCH_OUT_DIR` | Results root (default `data/benchmarks/`, gitignored) |

---

## 3. The order of work

1. **`python -m tests.bench list`.** Confirm which slots resolve and which suites have arms.
2. **Spike** (a few tiny calls per model, cents in total):
   ```bash
   python -m tests.bench spike --yes
   ```
   - For every Bedrock slot that's set, it checks: plain text, a system block, `temperature`, `maxTokens` 32,768, forced and auto tool choice, an image, (Claude) an effort field, and then the real `BedrockProvider` path with a structured probe and a short threat-modelling prompt. It also lists the account's foundation models and inference profiles.
   - Output goes to `data/benchmarks/spike-<date>.md` and `.json`, with **the verbatim error text** for each failed check.
   - Use it to fix up model IDs, set `BENCH_IMAGES_<SLOT>`, and drop models that can't do tool use. Report the table to the user.
3. **Prices.** Read each in-scope model's price from https://aws.amazon.com/bedrock/pricing/ for your region (and the OpenAI pricing page for the direct arm). Enter them in `prices.json` with `source` and `read_on`. A model without a price is "unpriced": its cost shows as n/a and `run` refuses it unless you pass `--allow-unpriced`.
4. **Estimate and get approval:**
   ```bash
   python -m tests.bench plan all
   ```
   This prints pipeline runs, tokens and cost per arm, from measured token footprints plus a 25% margin; real runs vary ±50%. **Send this table to the user and wait for approval.** They may cut suites or reps.
5. **Run, in this order**, stopping to report after each step:
   1. `e2e-degraded` (no-LLM arms cost nothing).
   2. `e2e-cli`, one run per model. Drop or flag any model that fails its gates before spending more on it.
   3. `e2e-web`, `e2e-enrich`, `e2e-maestro`, `e2e-code`.
   4. `mc` (model comparison).
   5. `bm2-routing`, `bm4-diagrams`, `bm5-iterations`, `bm3-enrich-routing`.
   6. `bm10-demo` (on the machine the commands will be shown on), `bm13-flagship`.

   ```bash
   python -m tests.bench run e2e-cli --yes --max-cost 5
   python -m tests.bench report e2e-cli
   ```

   `run` resumes: finished `(arm, rep)` pairs are skipped and failed ones are retried. `--only <arm-id>` runs one arm, and `--reps N` overrides the suite's rep count.
6. **No-LLM suites,** run directly:
   ```bash
   pytest -m live tests/live/test_attack_mapping_golden.py -v
   pytest -m live tests/live/test_deps_benchmark.py -v
   ```
   Run the dependency benchmark on Windows and Linux at the same time; Windows has an unresolved concurrent-run mismatch on 3 packages.

---

## 4. Safety rails built into the runner

- **Budget:**
  - `run` checks each run's estimate against the remaining cap before starting it and stops before crossing it.
  - Spend is tracked from real token usage × the price file.
  - Unpriced models are refused by default.
- **Timeouts:** each run is its own subprocess. On timeout the whole process tree is killed (`taskkill /T /F` on Windows), so a hung `aiosqlite` thread can't stall the batch. The run is recorded as `timeout`.
- **Isolation:** every run gets a scratch SQLite DB inside its run directory, so the dev database is never touched.
- **No secrets in artifacts:** only allow-listed settings (`AWS_REGION`, `AWS_PROFILE`, effort, fast-model and iteration settings) are recorded.
- **Concurrency is 1.** Don't parallelise runs of the same model: timings get skewed and Bedrock throttles.

---

## 5. Suites

Run `list` for the live view. Arms whose slot isn't set are skipped.

| Suite | What | Gates / metrics |
|---|---|---|
| `e2e-cli` | Every model, full input (description + 3 diagrams + manifest/lockfile, deps `both`, scoring `both`), `-n 2`; then `simple`/`sarif`/`markdown`/`pdf` exported from the saved model (no extra LLM cost) | completed; no rule-engine fallback; LLM, rule-engine and exactly 7 dependency threats; 1 image on each extraction call for image-capable models, none plus a skip event for text-only ones; 3 diagrams saved in order; SARIF 2.1.0 with a physical `locations[0]` on every result; PDF has text; Markdown has ATT&CK and CVSS lines; every CVSS vector parses and matches its stored score; no Semgrep processes left |
| `e2e-web` | Real server + API: create → run with uploads (SSE) → diagram routes → exports → re-run with no upload → re-run with 1 diagram. **3 pipeline runs per arm** | SSE completes; persisted threats = SSE total; list route omits image bytes and the single route returns them; re-run reuses the 3 stored diagrams (seen in the call log); uploading 1 replaces the set |
| `e2e-enrich` | `--enrich`, `-n 1` | an attack tree and a test suite for every threat; exports valid |
| `e2e-maestro` | MAESTRO + STRIDE on `examples/maestro-example-rag-chatbot.md` | both frameworks present |
| `e2e-code` | `--code $BENCH_CODE_REPO` | the `summarize_code` step ran |
| `e2e-degraded` | Unreachable provider (Ollama on a dead port, no spend); a 20 s dependency deadline; a text-only model + PNG | fallback reported; partial dependency results with no orphans; no 400 from images |
| `mc` | Every model as both main and fast, full input, `-n 2`, 3 reps | time, tokens, cost, iterations, threats by source and STRIDE category, CVSS validity, ATT&CK coverage, reliability events, image/flow-only components; quality against the checklist (§7) |
| `bm2-routing` | Routing off vs on (main/fast from env), no diagrams, `-n 3`, 3 reps | **per-step** cost and latency (the report prints the comparison table); whole-run totals are noise at n = 3 |
| `bm3-enrich-routing` | Same with `--enrich`, 2 reps | all four fast-eligible steps |
| `bm4-diagrams` | 3 diagrams, `-n 1`: extraction on fast vs on main, 3 reps | how often the secrets manager becomes an asset and the dead-letter queue shows up |
| `bm5-iterations` | `-n 5` with `MIN_ITERATIONS=5`, 3 reps | new non-duplicate threats per iteration |
| `bm10-demo` | The 3 standard demo commands, 5 reps each | wall time p50/p90, retries, fallbacks |
| `bm13-flagship` | Opus 5.5 and Fable 5.1: full input + `--enrich` (+ code if set) | per-step tokens by model, time, counts, refusals |

Each run directory (`data/benchmarks/<suite>/<arm>/rep-N/`) contains:
- `paranoid.db`: the scratch DB;
- `out.json`: the full CLI output, including the event stream;
- `calls.jsonl`: one line per LLM call, with image count, diagram tags, probe terms in the prompt, timing and error;
- `stdout.log` / `stderr.log`;
- the exports;
- `run.json`: metadata (arm, CLI args, exit code, times, exports).

`<suite>/results.jsonl` holds one metrics row per run, and `report` writes `data/benchmarks/<suite>-<date>.md`.

---

## 6. Known issues that affect results (check before trusting a number)

| Issue | Effect | Status to check |
|---|---|---|
| **Forced tool choice on Claude 5.x on Bedrock.** Opus 5.5, Sonnet 5.5 and Fable 5.1 reject forced `toolChoice` | Without the fix, every step on those models fails and falls back to the rule engine | **PR #124** (`fix/bedrock-tool-choice`). Make sure it's merged into the checkout you run. The spike's `forced_tool` vs `auto_tool` columns and a "rejects forced tool choice" log line confirm the behaviour |
| **Images to text-only Bedrock models.** The pipeline only skips images for the `ollama` provider | gpt-oss, Qwen and DeepSeek may 400 on extraction whenever the PNG is attached | Open (planned fix: per-model image capability on providers). Until then, run text-only models in `e2e-degraded` first; if they 400, report it and run them on Mermaid-only inputs |
| **No effort control on Bedrock.** `ANTHROPIC_EFFORT` only reaches the direct Anthropic provider | Claude on Bedrock runs at its own default effort (Opus 5.5 `medium`, Sonnet 5 `high`), so comparisons aren't effort-matched | Open (planned: pass effort through `additionalModelRequestFields`). The spike's `effort_field` column says whether Bedrock accepts it. State the effective effort in every report |
| **No prompt caching on Bedrock** in Paranoid's provider | Bedrock costs are higher than the direct-API numbers on record; don't compare them directly | Open (optional enhancement) |
| **Refusals look like format errors.** A refusal or content filter shows up as "Bedrock returned no tool_use block" | Refusal counts are approximate | Open (planned: a distinct refusal error). Count "no tool_use block" errors in `calls.jsonl` separately |
| **`tests/test_pipeline_e2e.py` is broken.** It still passes `diagram_data=`, which no longer exists | It fails if run | Don't use it; the suites here replace it |

---

## 7. Benchmarks with extra handling

- **Model-comparison quality** (`tests/bench/quality.py` + `fixtures/mediadrop-checklist.json`):
  - 18 reference threats for MediaDrop, each tagged with the input it comes from.
  - The checklist is a **draft awaiting human review**, and its match threshold (0.75 cosine) is a **placeholder**. Calibrate it on one hand-graded run per model family before reporting recall.
  - Matching uses the local fastembed model (`BAAI/bge-small-en-v1.5`), not an LLM judge.
  - `python -m tests.bench spotcheck mc` writes a blinded CSV (plus a separate key file) for a human to grade.
- **Malware recall** (`BENCH_MALWARE_DIR`): 10–20 known-malicious npm tarballs from public incident archives. **Handle them as inert files only:** never `npm install`, never extract into the repo, never execute, never commit. The scanner adapter for this benchmark isn't built yet (`list` shows it as pending).

---

## 8. Platform notes (Windows)

- When building the web UI in Git Bash, prefix `MSYS_NO_PATHCONV=1`, or `VITE_BASE=/app/` gets rewritten into a Windows path.
- Files written by Python in text mode get CRLF line endings. Strip `\r` before using them in shell loops.
- A `pip install -U` can upgrade `opentelemetry-api` past what the pip-installed Semgrep accepts. Every scan then fails on a warning printed to stdout. Run `pytest tests/test_deps_scanner.py` after any environment refresh; pin `opentelemetry-api==1.37.0` if it breaks.
- Anything that opens the shared DB connection must close it, or the process hangs after finishing. The runner's timeout and tree-kill cover this, but a run that ends as `timeout` right after `complete` is this, not a slow model.

---

## 9. Reporting back

After each step in §3, give the user:
- the `report` Markdown, or the spike table;
- the spend so far against the cap;
- any gate failure, with its detail line;
- anything in §6 that turned out true or false on this account.

Quote numbers with their n and date, as median [min–max]. Say "indicative" for n < 3, and don't present whole-run cost differences at n = 3 as findings. Curated results move into the repo's documentation only through a reviewed docs PR. Raw artifacts stay in `data/`.

---

## 10. Harness layout

| Module | Role |
|---|---|
| `config.py` | Env loading, model slots, settings |
| `matrix.py` | Suites and arms, built from env |
| `estimate.py` | Token footprints and pre-run cost estimates |
| `prices.py` | Price table and cost arithmetic |
| `run_one.py` | One CLI run in a subprocess, with per-call logging and exports |
| `web_server.py`, `web_driver.py` | The web/API-path executor |
| `runner.py` | Suite execution: budget, resume, timeout, tree-kill |
| `collect.py` | Run directory → metrics row |
| `gates.py` | E2E pass/fail checks |
| `report.py` | Markdown reports |
| `quality.py` | Checklist matching and the spot-check sheet |
| `spike.py` | The capability spike |
| `__main__.py` | The command line |
