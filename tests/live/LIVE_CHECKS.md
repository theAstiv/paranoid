# Live checks that need a real provider

Self-contained runbook for the checks that no mock can cover. It needs only a clone of this repo and
AWS credentials with Bedrock access: nothing from `.claude/`. Every check here makes real, paid model
calls, so **get the person who owns the account to approve the spend before running anything** and
report results back in the format at the end.

| # | Check | Bug | Needs | Approx. cost |
|---|---|---|---|---|
| 1 | Pre-flight checks: a `temperature` rejection on two parallel calls is retried, not raised | BB-32 | Bedrock, Sonnet 5.5 | $0.5–1 |
| 2 | Loan-agent MAESTRO run: `generate_threats` no longer hits the token ceiling | BB-33 | Bedrock, Sonnet 5.5 | $0.5–1 per run, up to 3 runs |
| 3 | Threats carry the iteration that produced them | BB-30 | Bedrock, Sonnet 5.5 (reuse a run from 1 or 2) | $0 extra |

All three checks can share runs: each run of the loan-agent example below covers checks 1, 2 and 3.
Check 3 only means something on a build that includes the BB-30 fix (see "Which build").

## Setup

```bash
git clone https://github.com/theAstiv/paranoid.git && cd paranoid
git checkout main && git pull          # see "Which build" below
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
```

Python 3.12+. Put the settings in `.env` at the repo root (it is gitignored; never commit it):

```ini
DEFAULT_PROVIDER=bedrock
AWS_REGION=us-east-2
# AWS_PROFILE=<profile with Bedrock access>   (or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN)
DEFAULT_MODEL=us.anthropic.claude-sonnet-5-5
ANTHROPIC_EFFORT=medium
DB_PATH=./data/livecheck.db
LOG_LEVEL=info
```

- Leave `FAST_MODEL_BEDROCK` empty: no fast-model routing, so every call goes to Sonnet 5.5 and the
  checks stay comparable.
- **Refresh AWS credentials right before each run.** Temporary credentials that expire mid-run make the
  pipeline fall back to the rule engine: exactly **17 threats, $0, under a minute**. A 17-threat result
  is an invalid run, not a pass; discard it and re-run.
- A scratch `DB_PATH` keeps these runs out of any other database.

Sanity check before spending: `paranoid --help` works and `aws sts get-caller-identity` succeeds (or
whatever your credential chain is).

## Which build

Run on current `main`. Checks 1 and 2 verify fixes that are already merged (BB-32 in #167, BB-33 in
#168). Check 3 verifies BB-30; skip it, or mark it "not run", unless `git log --oneline | grep -i
"BB-30"` shows the BB-30 fix is in your checkout. Write the commit you ran
(`git rev-parse --short HEAD`) in the report.

## The run (covers checks 1, 2 and 3)

```bash
mkdir -p livecheck
paranoid run examples/maestro-example-loan-agent.md \
  -n 2 \
  --provider bedrock --model us.anthropic.claude-sonnet-5-5 \
  -d examples/maestro-loan-agent-architecture.mmd \
  --format full -o livecheck/run1.json 2>&1 | tee livecheck/run1.log
```

`-n 2` matters: one iteration cannot show a lost second iteration (check 2) or two iteration numbers
(check 3). Expect about 4 minutes and roughly 30–35 threats. On a slow or throttled account allow up to
8 minutes before calling it hung.

Then look at the log:

```bash
grep -n -i "rejects the .temperature\|rejects forced tool choice\|gap analysis failed\|truncated\|provider_offline\|fallback\|Traceback" livecheck/run1.log
```

### Check 1 · BB-32 (a second concurrent `temperature` rejection is retried)

Background: Sonnet 5.5 on Bedrock rejects `temperature`. The only LLM calls a run makes in parallel
are the two pre-flight checks, one on the description and one on the assumptions (`analyze_bundle()`
in `backend/pipeline/pre_flight.py`). They run first, on a provider that has not seen a rejection yet,
so both can be in flight with `temperature` when the first rejection arrives. Before the fix the
second call's identical rejection was raised. Pre-flight catches that error and falls back to its
deterministic checks, so the run still completes and no step is reported as failed: the only sign is
a warning in the log.

A hybrid (`--stride-maestro`) run does not exercise this. Its STRIDE and MAESTRO `generate_threats`
calls run one after the other, not in parallel, and on this example (a MAESTRO template) the flag has
no effect at all.

The log grep above covers the warnings. Then count the pre-flight calls (pre-flight may skip one or
both LLM calls when its deterministic checks already found enough gaps):

```bash
python - <<'PY'
import json, sqlite3
c = sqlite3.connect("data/livecheck.db")
m = c.execute("select id, usage_summary from threat_models order by created_at desc limit 1").fetchone()
steps = json.loads(m[1] or "{}").get("steps", [])
calls = [u["calls"] for s in steps if s["step"] == "pre_flight" for u in s["usage"]]
print("model:", m[0])
print("pre_flight calls:", calls or "none (no pre_flight step: no LLM call was made)")
PY
```

- **Pass:**
  - `pre_flight calls` is **2 or more**. Only an answered call counts, so 2 means both checks reached
    the model and got an answer.
  - **No** `LLM gap analysis failed` or `LLM assumptions gap analysis failed` line in the log.
  - A line like ``Model … rejects the `temperature` parameter — omitting it for the rest of this provider instance's calls`` appears **once per provider instance** (a few lines at most, not one per call).
  - The run completes with `stopped_reason` of `max_iterations` or `gap_satisfied`, no traceback, and a
    threat count well above 17.
- **Fail:** an `LLM gap analysis failed` or `LLM assumptions gap analysis failed` line whose error is
  about `temperature`. Copy the line into the report.
- **Not exercised (not a pass; say so):**
  - `pre_flight calls` is 1 or none: fewer than two calls were in flight, so there was no race.
  - The log has **no** `temperature` line at all: the model did not reject it.
  - A `gap analysis failed` line for another reason (throttling, expired credentials). Copy it.
- **Also expected, not an error:** ``Model … rejects forced tool choice — using auto tool choice …``
  once per provider instance.

Every run counts for check 1, so the three check 2 runs give three tries.

### Check 2 · BB-33 (`generate_threats` ceiling)

Background: `generate_threats` starts at 16,384 output tokens and, with thinking on, could use the whole
budget on thinking. The auto-bump ceiling was also 16,384, so a cut-off call never got a bigger attempt
and the run ended as `provider_offline` (rule-engine fallback). The ceiling is now 32,768 and the call
timeout scales with it (480 s at 32,768). The failure was **intermittent** (the immediate re-run was
fine), so one clean run is weak evidence: run it **3 times** (`run1`, `run2`, `run3`) unless told to
stop early.

- **Pass (each run):** completes with 2 iterations, a normal threat count (about 30–35), stop reason not
  `provider_offline`, and no `truncated` line naming a ceiling it could not get past.
- **Acceptable:** a `truncated … blocks=[…]` warning followed by a successful, larger retry. That is the
  new behaviour working. Copy the line into the report; its `blocks=` list says whether `thinking`
  filled the budget.
- **Fail:** `provider_offline`, exactly 17 threats, only one iteration where two were expected, or a
  truncation warning at 32,768 tokens that ends the step. Keep the log and the JSON.

### Check 3 · BB-30 (iteration number on threats)

Background: every LLM threat was saved with `iteration_number = 1`, even ones a second iteration
produced. After the fix a 2-iteration run has threats stamped 1 and 2. Rule-engine and seed threats are
a separate case; see below.

```bash
python - <<'PY'
import sqlite3
c = sqlite3.connect("data/livecheck.db")
m = c.execute("select id, title, iteration_count from threat_models order by created_at desc limit 1").fetchone()
print("model:", m)
for row in c.execute(
    "select source, iteration_number, count(*) from threats where model_id=? group by 1,2 order by 1,2", (m[0],)
):
    print(row)
PY
```

- **Pass:** the `source` that holds the LLM threats (look at the distinct values printed) shows rows for
  **both** `iteration_number` 1 and 2 on a run that did two iterations.
- **Fail:** only `1` appears for LLM threats on a 2-iteration run (the old behaviour).
- **Not a failure:** rule-engine or dependency threats carrying a single value, as long as the report
  says what they showed.
- If the DB has no `threat_models` / `threats` tables by those names, report the error text; do not
  guess other names.

## What to send back

Paste this filled in, plus `livecheck/*.log` and `livecheck/*.json` (the logs can hold account IDs in
ARNs: skim before sharing; they never contain keys):

```
commit:            <git rev-parse --short HEAD>
date / region:     <…> / <region>
model:             us.anthropic.claude-sonnet-5-5 (effort medium)
run                | threats | iterations | stopped_reason | wall s | cost (Run Summary) | notes
run1               |         |            |                |        |                    |
run2 / run3        |         |            |                |        |                    |
check 1 (BB-32):   PASS | FAIL | NOT EXERCISED   — per run: pre_flight calls, temperature and "gap analysis failed" log lines: <paste>
check 2 (BB-33):   PASS | FAIL                   — truncation lines, if any: <paste>
check 3 (BB-30):   PASS | FAIL | NOT RUN (fix not in build) — query output: <paste>
anything odd:      <fallbacks, 17-threat runs and why, timeouts>
```

## Stop conditions

- A run ends with exactly 17 threats: refresh credentials, re-run once, and say so in the report.
- Two runs in a row fail check 1 or 2 with a raised error: stop, send the logs, do not keep spending.
- Do not change code, prompts or model settings to make a check pass. These are observations of the
  shipped behaviour.
