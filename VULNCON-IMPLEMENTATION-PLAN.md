# VULNCON Arsenal — Tier 1 + Tier 2 Implementation Plan

Pre-event work items for the June 12-13 Bengaluru demo. Tier 1 items are
demo-blockers. Tier 2 items separate "impressive" from "forgettable."

---

## Tier 1 — Demo-blockers

### 1.1  First-run / no-API-key gate in the wizard

**Problem:** `App.svelte:41` redirects to `/settings` on `first_run === true`,
and `Settings.svelte:181` shows an amber welcome banner. But neither the
wizard (`NewModel.svelte`) nor the pipeline start path (`Results.svelte`)
checks whether a provider key is actually configured. A user (or a demo
audience volunteer) who skips Settings and hits "Run" gets a confusing SSE
error when the provider constructor raises `ValueError: api_key required`.

**What exists:**
- `GET /api/config/` returns `first_run`, `anthropic_api_key_set`,
  `openai_api_key_set`, and `anthropic_api_key_source` / `openai_api_key_source`.
- `App.svelte` fetches config on mount and pushes to `/settings` if `first_run`.
- The `config` Svelte store is populated on boot and after Settings save.

**What to build:**

1. **`NewModel.svelte` — provider-guard on Step 7 (Review & Run).**
   Read `$config` store. If the provider selected for this model has no key
   set (`$config.anthropic_api_key_set === false` for anthropic, etc.), show
   a non-dismissible warning card on Step 7 and disable the Run button.
   Message: "No API key configured for {provider}. Go to Settings to add one."
   Link directly to `/settings`. This is ~20 lines in the Step 7 template block.

2. **`Results.svelte` — guard on `rerun()`.**
   Same check before firing `subscribeToRun()`. If no key, show a notification
   toast and abort. This catches the edge case where someone manually navigates
   to a model page and clicks Re-run.

3. **No backend changes.** The backend already returns the right flags.
   The fix is purely frontend gating.

**Files changed:**
- `frontend/src/routes/NewModel.svelte` (~20 lines in Step 7 block)
- `frontend/src/routes/Results.svelte` (~10 lines in `rerun()`)

**Tests:**
- Manual: fresh `.env` with no keys, open `/models/new`, advance to Step 7,
  confirm Run button is disabled with a clear message.
- Manual: paste key in Settings, go back to wizard, confirm Run button enables.

**Effort:** 1 hour.

---

### 1.2  Attack tree rendering — Mermaid fallback hardening

**Problem:** The stale-bundle crash (P1) is fixed. But `AttackTree.svelte:48`
has a second failure mode: if the LLM returns syntactically invalid Mermaid
(missing semicolons, illegal node IDs, unsupported diagram type), `mermaid.render()`
throws and the `catch` block on line 55 falls back to `<pre>{source}</pre>`.
This is functional but ugly — raw Mermaid syntax means nothing to a non-technical
reviewer.

**What exists:**
- `AttackTree.svelte:48-58` — `renderMermaid()` with try/catch.
- On error, raw source is dumped into `svgContainer.innerHTML` as a `<pre>` block.

**What to build:**

1. **Improve the fallback UI.** Replace the bare `<pre>` fallback with a
   styled card that says "Mermaid rendering failed" with a "Show raw source"
   toggle and a "Regenerate" button. The user sees a clear call-to-action
   instead of a wall of syntax.

2. **Sanitize common LLM Mermaid mistakes before rendering.**
   Add a `_sanitizeMermaid(source)` function that:
   - Strips markdown fences (` ```mermaid ` / ` ``` `) — LLMs often wrap output
   - Removes `&nbsp;` / `&amp;` HTML entities that break the parser
   - Replaces `---` (HR) with `-->` when it appears in an arrow context
   - Runs this before `mermaid.render()`, not only on error

3. **Render the Mermaid diagram ID with a timestamp suffix** to avoid
   `mermaid.render()` collisions when the user clicks Regenerate without
   a page reload (`tree-${params.id}-${Date.now()}`).

**Files changed:**
- `frontend/src/routes/AttackTree.svelte` (~30 lines)

**Tests:**
- Unit: `_sanitizeMermaid()` strips fences, entities, and malformed arrows
  (add to `frontend/tests/AttackTree.test.js` or inline).
- Manual: generate an attack tree, verify Mermaid renders. Click Regenerate,
  verify the new tree replaces the old without errors. Deliberately corrupt
  the `mermaid_source` in the DB and reload — verify the fallback card shows.

**Effort:** 1.5 hours.

---

### 1.3  Persist + surface iteration gap analysis post-run

**Problem:** The iterative gap analysis is the #1 differentiator vs one-shot
tools. During the SSE stream, gap summaries appear in `PipelineProgress.svelte`
as `evt.message` text. But `gaps: list[str]` in `runner.py:199` is an
in-memory list that is discarded after the pipeline exits. No gap data is
persisted to SQLite. After the run, Results, Review, Library, and all export
formats show zero gap information.

**What exists (where gap data lives today):**
- `runner.py:199` — `gaps: list[str] = []`, accumulated during the iteration loop.
- `runner.py:716-722` — gap_analysis completed events carry `data.gap` (full prose).
- `runner.py:716` — `event.data = {"stop": False, "gap": gap_result.gap}`.
- `_persist_pipeline_event()` in `routes/models.py:168` — only handles
  `EXTRACT_ASSETS`, `EXTRACT_FLOWS`, and `COMPLETE` events. Gap events are ignored.
- CLI `run.py` — `gap_result` from `analyze_bundle` is used for SARIF, but
  the per-iteration gap prose is never exported.

**What to build:**

#### Backend

1. **Schema migration — add `gap_summaries` column to `threat_models`.**

   ```sql
   ALTER TABLE threat_models ADD COLUMN gap_summaries TEXT;
   ```

   Stores a JSON array of strings (one per iteration gap). Follows the existing
   migration pattern in `schema.py:252-263` (try/except on duplicate column).

2. **Persist gaps from SSE events.**

   In `_persist_pipeline_event()`, accumulate `GAP_ANALYSIS` completed events
   into a module-level dict keyed by model_id. On the `COMPLETE` event, flush
   the accumulated gaps to the `gap_summaries` column as a JSON array.

   Alternatively (simpler, no module state): collect gaps on the `COMPLETE`
   event from `event.data`. This requires the runner to include the `gaps` list
   in the complete event's `data` dict.

   **Preferred approach:** Add `gaps` to the `COMPLETE` event data in `runner.py`.
   The runner already passes `threats`, `stopped_reason`, etc. in the complete
   event. Adding `gaps` is a one-line change. Then `_persist_pipeline_event()`
   reads `event.data.get("gaps")` and calls `crud.update_threat_model()` with
   the JSON-serialized list.

   ```python
   # runner.py — in the COMPLETE event (around line 770)
   data={
       ...,
       "gaps": gaps,  # list[str] — add this
   }
   ```

   ```python
   # routes/models.py — _persist_pipeline_event, COMPLETE handler
   gap_list = event.data.get("gaps")
   if gap_list:
       await crud.update_threat_model(
           model_id, gap_summaries=json.dumps(gap_list)
       )
   ```

3. **Expose gaps in the model GET response.**

   `crud.get_threat_model()` already returns all columns from `threat_models`.
   The `gap_summaries` column will appear as a JSON string. Parse it to a list
   in the route's response serialization (or let the frontend parse it).

4. **CLI persistence path.**

   `persist.py:persist_pipeline_result()` — accept an optional `gap_summaries`
   parameter. The CLI runner passes the `gaps` list from the pipeline.

5. **Markdown export.**

   `export/markdown.py` — add a "## Gap Analysis (Per Iteration)" section after
   the summary table. Each gap gets an `### Iteration N` heading with the prose.
   Only rendered when `gap_summaries` is non-empty.

6. **PDF export.**

   `export/pdf.py` — add a "Gap Analysis" section between the summary table
   and the threat details. Same content as markdown.

#### Frontend

7. **`Results.svelte` — gap analysis section after pipeline progress.**

   After the pipeline completes (model status = completed), show a collapsible
   "Iteration Gaps" card. Fetch gaps from `model.gap_summaries` (parsed JSON
   array). Each iteration gets a numbered heading and the prose summary. If
   no gaps (single iteration, or gap_satisfied on first pass), show
   "Coverage was sufficient after iteration 1 — no gaps identified."

   ```svelte
   {#if model.gap_summaries?.length > 0 && !$pipelineRunning}
     <div class="bg-white rounded-xl border border-slate-200 p-5">
       <h2 class="text-sm font-semibold text-slate-700">Iteration Gap Analysis</h2>
       {#each model.gap_summaries as gap, i}
         <div class="mt-3">
           <p class="text-xs font-medium text-slate-500">Iteration {i + 1}</p>
           <p class="text-sm text-slate-700 mt-1">{gap}</p>
         </div>
       {/each}
     </div>
   {/if}
   ```

8. **`Library.svelte` — optional gap indicator.**

   On each model row, show a small "N gaps" badge if `gap_summaries` has
   entries. Clicking expands to show the prose. Low priority — the main
   surface is Results.

**Files changed:**
- `backend/db/schema.py` — migration block (~8 lines)
- `backend/db/crud.py` — accept `gap_summaries` in `update_threat_model()` and
  `create_threat_model()` (~5 lines)
- `backend/pipeline/runner.py` — add `"gaps": gaps` to COMPLETE event data (~1 line)
- `backend/routes/models.py` — handle gaps in `_persist_pipeline_event()` (~10 lines),
  parse `gap_summaries` in model GET response (~3 lines)
- `backend/db/persist.py` — accept + persist `gap_summaries` param (~5 lines)
- `cli/commands/run.py` — pass `gaps` to `persist_pipeline_result()` (~2 lines)
- `backend/export/markdown.py` — gap analysis section (~15 lines)
- `backend/export/pdf.py` — gap analysis section (~20 lines)
- `frontend/src/routes/Results.svelte` — gap analysis card (~25 lines)

**Tests:**
- `tests/test_pre_flight.py` or new `tests/test_pipeline_gaps.py`:
  - `test_complete_event_includes_gaps_list`: mock a 2-iteration run, verify
    the COMPLETE event data contains `gaps` with 1 entry.
  - `test_persist_pipeline_event_writes_gap_summaries`: mock COMPLETE event
    with gaps, verify `crud.update_threat_model` called with JSON array.
- `tests/test_export_markdown.py`:
  - `test_markdown_includes_gap_analysis_section`: pass `gap_summaries`,
    verify output contains "## Gap Analysis" and iteration headings.
- `tests/test_export_pdf.py`:
  - `test_pdf_includes_gap_analysis`: pass `gap_summaries`, verify the PDF
    bytes are non-empty (deeper inspection not worth the effort).
- Manual: run a 2-iteration sample, navigate to Results, verify the gap
  analysis card shows. Export to markdown, verify the section appears.
  Run a 1-iteration sample, verify "no gaps" message.

**Effort:** 3 hours (2h backend, 1h frontend).

---

## Tier 2 — Demo quality

### 2.1  PDF export quality audit + fixes

**Problem:** The PDF is what attendees take away from the demo (or screenshot
during the talk). reportlab PDFs from auto-generated code often have:
- Unbroken long strings (threat descriptions, mitigation lists) that overflow
  table cells or get clipped.
- Missing or inconsistent severity colour coding (the markdown export has
  coloured severity badges; the PDF likely doesn't).
- No page numbers or headers after page 1.
- DREAD score table may overflow on narrow cells.
- Mitigations rendered as a single comma-separated string instead of a
  bulleted list.

**What exists:**
- `backend/export/pdf.py` — reportlab platypus layout with `SimpleDocTemplate`,
  proper styles, header/footer, summary table, grouped threats by category,
  and optional attack tree / test case sections. The structure is sound.
- `_TABLE_STYLE_BASE` on line 152 — defines alternating row backgrounds, grid,
  and font sizes. Font size is 8pt which is small but acceptable.
- `_threat_flowables()` — builds per-threat detail blocks (need to read this).
- No page numbers (SimpleDocTemplate doesn't add them by default).

**What to build:**

1. **Generate a PDF from one of the India samples and visually inspect it.**
   This is the first step — the problems may be better or worse than expected.

2. **Fix whatever is broken.** Expected fixes based on code review:
   - **Page numbers:** Add an `onPage` / `onLaterPages` callback to
     `SimpleDocTemplate.build()` that draws "Page N" in the footer.
   - **Long strings:** Wrap threat descriptions, mitigations, and target
     fields in `Paragraph()` objects (which auto-wrap) instead of raw strings
     in table cells. Check if `_threat_flowables()` already does this.
   - **Mitigations as bullet list:** If mitigations are rendered as a single
     string, split on the JSON array boundary and render as separate Paragraphs
     with bullet prefixes.
   - **Severity colour:** Add conditional background colour to the severity
     cell (red for Critical, orange for High, yellow for Medium, grey for Low).
   - **DREAD table width:** Ensure the 5 DREAD columns fit without overflow.

3. **Add the gap analysis section** (from 1.3 above) between the summary
   table and the threat details.

**Files changed:**
- `backend/export/pdf.py` — audit and fix (~30-50 lines depending on findings)

**Tests:**
- `tests/test_export_pdf.py` — existing tests verify non-empty bytes output.
  Add one test with a realistic threat list (use the UPI sample fixture) and
  verify the output is > 10KB (catches blank-page bugs).
- Manual: open the generated PDF in a browser, scroll through, verify no
  overflow, no clipped text, page numbers present, severity colours visible.

**Effort:** 2-3 hours (1h audit, 1-2h fixes).

---

### 2.2  Bulk review actions on Review page

**Problem:** Clicking through 24 threats one-by-one during a demo is painful
to watch. Need faster batch operations.

**What exists:**
- `Review.svelte:54-63` — `approveAll()` function that approves all pending
  threats in one batch. An "Approve all pending (N)" button is shown when
  `pendingThreats.length > 0` (line 100-107).
- Individual `handleApprove` and `handleReject` per threat card.
- Filter tabs: all, pending, approved, rejected (line 83-98).

**What's missing:**
- **"Reject all pending"** button alongside approve-all. Same pattern.
- **Severity-filtered batch actions.** "Approve all Critical/High" and
  "Reject all Low" are the most useful for a demo — show the reviewer
  making a risk-based batch decision.

**What to build:**

1. **Add `rejectAll()` function.** Mirror `approveAll()` on line 54. Same
   pattern: optimistic UI update, then `Promise.all(pending.map(...))`.

2. **Add severity-filtered approve/reject.** Two dropdown buttons:
   - "Approve by severity" → Critical, High, Medium, Low options
   - "Reject by severity" → same options
   Each calls `Promise.all()` on the filtered subset.

   For the demo, the simplest version is two flat buttons:
   - "Approve Critical + High" (most common demo action)
   - "Reject Low" (second most common)
   These are faster to implement than a full dropdown and cover the demo flow.

3. **Counts in the bulk buttons.** "Approve Critical+High (7)" so the
   audience sees the scope of the action before it fires.

**Files changed:**
- `frontend/src/routes/Review.svelte` (~30 lines)

**Tests:**
- Manual: run a sample, go to Review, click "Approve Critical+High", verify
  the count updates and the threats move to the approved tab. Click "Reject
  Low", verify same. Click "Approve all pending" to mop up the rest.

**Effort:** 1 hour.

---

### 2.3  Ollama provider end-to-end verification

**Problem:** "Runs fully locally, no data leaves your machine" is the line
that lands hardest with a security audience. The Ollama provider
(`backend/providers/ollama.py`) was NOT affected by the Structured Outputs
migration (it uses `format: "json"` + `model_json_schema()` in the prompt,
not the OpenAI `parse()` API). But it hasn't been tested against the new
extraction `max_tokens` values (8192 for assets, 32768 for flows) and the
Ollama API's `num_predict` parameter has different behaviour from OpenAI's
`max_tokens`.

**What exists:**
- `ollama.py:107-119` — calls `/api/generate` with `format: "json"` and
  `num_predict` in `options`. Schema is injected into the prompt text.
- `ollama.py:50-53` — default timeout is 120s.
- The provider uses `httpx.AsyncClient` directly, not the OpenAI SDK.
- No Structured Outputs equivalent — Ollama's `format: "json"` only
  guarantees valid JSON, not schema conformance (same limitation the old
  OpenAI path had). Required fields may be missing.

**What to verify:**

1. **Does Ollama respect `num_predict=32768`?** Check whether the model
   actually generates that many tokens or silently truncates. With llama3
   (8K context), `num_predict=32768` exceeds the context window — Ollama
   may clamp it silently. Need to test with a model that has a large enough
   context (llama3.1 8B has 128K context, or mistral-nemo has 128K).

2. **Does `format: "json"` produce schema-conformant output for the
   extraction models?** The prompt includes the full JSON schema, but
   smaller models may omit required fields (same issue we fixed for OpenAI).
   If this fails, add a `model_validate()` retry with `strict=False` so
   missing optional-ish fields get defaults rather than crashing.

3. **Timeout adequacy.** 120s may not be enough for `extract_flows` on a
   complex diagram with a local GPU. Ollama's generation speed depends on
   the hardware. If the laptop running the demo has a modest GPU, the
   UPI sample may take 3-5 minutes for `extract_flows`.

**What to build (if issues found):**

1. **Bump Ollama timeout to 300s** to match the worst-case generation time
   on a mid-range GPU.

2. **Add a Pydantic validation fallback.** If `model_validate()` raises
   `ValidationError`, try `model_validate()` again with the data dict
   but fill in missing required fields with defaults (empty strings,
   empty lists). This is a partial result rather than a pipeline crash.

3. **Document the model floor.** Add a note in CLAUDE.md: Ollama requires
   a model with >= 32K context window for dense MAESTRO samples. Recommend
   `llama3.1:8b`, `mistral-nemo`, or `qwen2.5:14b`.

**Files changed:**
- `backend/providers/ollama.py` — timeout bump + optional validation fallback
  (~15 lines)
- `.claude/rules/CLAUDE.md` — Ollama model recommendations (~5 lines)

**Tests:**
- Integration (requires local Ollama): run the UPI STRIDE sample with
  `--provider ollama --model llama3.1:8b --iterations 1`. Verify it
  completes without `ValidationError` or timeout.
- Unit: `tests/test_providers.py` — update existing Ollama mock tests if
  the validation fallback changes the error surface.

**Effort:** 0.5h verification + 0.5h fixes if needed = 1 hour max.

---

## Dependency graph

```
1.1 (API key gate)        ── independent ──────────────── can start immediately
1.2 (Attack tree)         ── independent ──────────────── can start immediately
1.3 (Gap persistence)     ── independent ──────────────── can start immediately
2.1 (PDF audit)           ── depends on 1.3 ────────────── gap section needs gaps in export
2.2 (Bulk review)         ── independent ──────────────── can start immediately
2.3 (Ollama verification) ── independent ──────────────── can start immediately
```

Items 1.1, 1.2, 1.3, 2.2, and 2.3 can run in parallel. Item 2.1 depends on 1.3
for the gap-analysis-in-export portion, but the PDF audit itself can start in
parallel — just add the gap section after 1.3 lands.

---

## Execution order (recommended)

| Order | Item | Effort | Running total |
|-------|------|--------|---------------|
| 1     | 1.3 Gap persistence    | 3h  | 3h   |
| 2     | 1.1 API key gate       | 1h  | 4h   |
| 3     | 1.2 Attack tree        | 1.5h| 5.5h |
| 4     | 2.2 Bulk review        | 1h  | 6.5h |
| 5     | 2.1 PDF audit          | 2-3h| 9h   |
| 6     | 2.3 Ollama             | 1h  | 10h  |

**Total: ~10 hours of focused work.**

Start with 1.3 because it's the largest item and unblocks the gap-in-export
portion of 2.1. Then 1.1 and 1.2 which are quick and independent. Finish with
2.1 (PDF audit) which is the most variable-effort item — depends on what the
audit reveals.

---

## CI checklist (run after all items land)

Per `.claude/rules/ci-checklist.md`:

```bash
# 1. Python lint
ruff check backend/ cli/ tests/
ruff format --check backend/ cli/ tests/

# 2. Python tests
cd c:/Users/Lenovo/Documents/github/paranoid
pytest tests/ -v --tb=short --ignore=tests/test_pipeline_e2e.py

# 3. Frontend tests
npm test --prefix frontend

# 4. Frontend build
npm run build --prefix frontend

# 5. Python package build + twine check
python -m build --outdir dist
python -m twine check dist/paranoid_cli-*.whl dist/paranoid_cli-*.tar.gz
```

Plus: `docker compose up --build -d`, wait for health, verify `/app` loads,
run one India sample end-to-end via the UI, and visually inspect the PDF export.
