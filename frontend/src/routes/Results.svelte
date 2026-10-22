<script>
  import { onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import { link } from 'svelte-spa-router'
  import {
    getModel, updateModel, getModelAssets, getModelFlows, getModelTrustBoundaries,
    createAsset, updateAsset, deleteAsset,
    createFlow, updateFlow, deleteFlow,
    createTrustBoundary, updateTrustBoundary, deleteTrustBoundary,
    subscribeToRun, followRun, getCommentCounts, getModelDependencies, listModelDiagrams, getModelDiagram,
    getMaestroCoverage,
  } from '../lib/api.js'
  import {
    currentModel, threats, pipelineEvents, pipelineRunning, abortRun, notify, config,
    currentProject, currentUser,
  } from '../lib/stores.js'
  import { canEditProject } from '../lib/utils.js'
  import PipelineProgress from '../components/PipelineProgress.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'
  import ResourceList from '../components/ResourceList.svelte'
  import Assignees from '../components/Assignees.svelte'
  import Comments from '../components/Comments.svelte'
  import EntityComments from '../components/EntityComments.svelte'
  import DependencyHeatmap from '../components/DependencyHeatmap.svelte'
  import MaestroCoverage from '../components/MaestroCoverage.svelte'
  import DiagramView from '../components/DiagramView.svelte'

  /** @type {{ id: string }} */
  export let params = {}

  let model = null
  let assets = []
  let flows = []
  let trustBoundaries = []
  let assetCommentCounts = {}
  let flowCommentCounts = {}
  let threatCommentCounts = {}
  let dependencyScans = []
  let maestroCoverage = null
  let diagrams = []
  let selectedDiagramId = null
  let diagramContentCache = {} // { [diagramId]: { content, media_type } }
  let diagramContentLoading = {} // { [diagramId]: true } — per id, so switching tabs mid-fetch can't let one id's `finally` clear another's flag
  let diagramContentError = {} // { [diagramId]: true } — a failed id is not retried automatically; see retryDiagram()
  // Not reset on a list reload (unlike the three above): a re-run with no new
  // upload keeps the same diagram ids, so a fetch already in flight when the
  // list reloads must still be recognized as in flight — otherwise the
  // reactive guard below sees a freshly-reset "not cached, not loading" id
  // and starts a duplicate request for it.
  let diagramFetchToken = {} // { [diagramId]: token }
  let nextDiagramFetchToken = 0
  let tabRefs = []
  $: selectedDiagram = diagrams.find(d => d.id === selectedDiagramId) ?? diagrams[0] ?? null
  $: selectedDiagramContent = selectedDiagram
    ? (selectedDiagram.kind === 'mermaid'
        ? selectedDiagram.content
        : (diagramContentCache[selectedDiagram.id]?.content ?? null))
    : null
  // The default-selected diagram (page load, or after a list reload) also needs
  // its content lazily fetched, not just an explicit tab click. A failed id is
  // excluded so a lasting error (404/403/500) doesn't retry forever.
  $: if (selectedDiagram && selectedDiagram.kind !== 'mermaid'
      && !diagramContentCache[selectedDiagram.id]
      && !diagramContentLoading[selectedDiagram.id]
      && !diagramContentError[selectedDiagram.id]) {
    selectDiagram(selectedDiagram.id)
  }
  /** @type {any} */ let assetsList
  /** @type {any} */ let flowsList
  /** @type {any} */ let boundariesList
  let loading = true
  let polling = false
  let pollTimer = null
  // 'in_progress' with no run behind it on the server: it was stopped by a
  // restart, or stuck before runs outlived their page (BB-71).
  let interrupted = false
  let stopFollowing = null

  $: stoppedReason = $pipelineEvents.find(e => e.step === 'complete')?.data?.stopped_reason ?? ''
  $: codeAnalysis = $pipelineEvents.find(e => e.step === 'summarize_code' && e.status === 'completed')?.data?.code_summary ?? model?.code_summary ?? null
  // RunUsage from the COMPLETE event's data.usage (backend/models/usage.py) — tokens
  // by model and the fast-model share, no price fields (decided 2026-10-01). Falls
  // back to the persisted `usage` field (threat_models.usage_summary) since
  // pipelineEvents is cleared on mount unless a pipeline run is actively streaming
  // (see switchModel), so a page reload after completion has no live SSE events.
  $: runUsage = $pipelineEvents.find(e => e.step === 'complete')?.data?.usage ?? model?.usage ?? null
  $: guard = runUsage?.coverage_guard ?? null
  // The run's N/A list is tag-based and saved with the run; the coverage panel is
  // computed from the threats. Don't list a category the panel shows as covered.
  $: coveredCategories = new Set(
    (maestroCoverage?.categories ?? []).filter((c) => c.status === 'covered').map((c) => c.category),
  )
  $: naMaestro = (guard?.na_maestro ?? []).filter((c) => !coveredCategories.has(c))
  const STOP_LABELS = {
    gap_satisfied: 'gap analysis satisfied',
    dedup_saturated: 'new threats were duplicates',
    max_iterations: 'max iterations reached',
    timeout: 'time limit reached',
    provider_offline: 'provider offline',
  }
  $: stepRows = (runUsage?.steps ?? []).map(s => ({ ...s, tokens: sumStepUsage(s.usage) }))

  // A step normally has one usage entry; a fast→main retry adds a second.
  function sumStepUsage(usage) {
    const t = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 }
    for (const u of usage ?? []) for (const k in t) t[k] += u[k] ?? 0
    return t
  }

  let _wasRunning = false
  $: {
    if (_wasRunning && !$pipelineRunning && model?.id === params.id) onRunEnded()
    _wasRunning = $pipelineRunning
  }

  // The wizard's run streams into the shared stores and nothing on this page
  // owns that stream, so the model loaded mid-run is stale when it ends (BB-137).
  let followingWizardRun = false

  function onRunEnded() {
    if (!followingWizardRun) { loadSupplementary(); return }
    followingWizardRun = false
    refreshModel(params.id)
  }

  async function refreshModel(id) {
    let refreshed
    try {
      refreshed = await getModel(id)
    } catch (err) {
      if (id === params.id) notify('error', `Failed to reload model: ${err.message}`)
      return
    }
    if (id !== params.id) return
    model = refreshed
    currentModel.set(refreshed)
    threats.set(refreshed.threats ?? [])
    await loadSupplementary()
  }

  // Load on mount and whenever only the route param changes: #/models/a -> #/models/b
  // keeps this component instance, so loading only on mount left model a showing.
  let loadedId = null
  $: if (params.id && params.id !== loadedId) switchModel(params.id)

  function resetForModel() {
    stopPolling()
    if (stopFollowing) { stopFollowing(); pipelineRunning.set(false) }
    interrupted = false
    followingWizardRun = false
    model = null
    loading = true
    assets = []; flows = []; trustBoundaries = []
    assetCommentCounts = {}; flowCommentCounts = {}; threatCommentCounts = {}
    dependencyScans = []
    maestroCoverage = null
    diagrams = []
    selectedDiagramId = null
    diagramContentCache = {}
    diagramContentError = {}
  }

  async function switchModel(id) {
    if (loadedId !== null) resetForModel()
    loadedId = id
    const alreadyRunning = get(pipelineRunning)
    if (!alreadyRunning) pipelineEvents.set([])
    let loaded
    try {
      loaded = await getModel(id)
    } catch (err) {
      if (id !== params.id) return
      notify('error', `Failed to load model: ${err.message}`)
      loading = false
      return
    }
    if (id !== params.id) return // another model was opened while this one loaded
    model = loaded
    currentModel.set(model)
    threats.set(model.threats ?? [])
    loading = false
    if (alreadyRunning) {
      // The run may have ended while the model was loading.
      if (!get(pipelineRunning)) await refreshModel(id)
      else if (model.status === 'in_progress') followingWizardRun = true
      return
    }
    if (model.status === 'in_progress') {
      attachToRun(id)
    } else if (model.status === 'completed' || model.status === 'failed') {
      await loadSupplementary()
    }
  }

  // The run is a background task on the server, so a page opened mid-run (after
  // a reload, or after leaving and coming back) picks up its live events.
  function attachToRun(id) {
    let failure = null
    let stopped = false
    pipelineEvents.set([])
    pipelineRunning.set(true)
    const abort = followRun(
      id,
      evt => {
        pipelineEvents.update(es => [...es, evt])
        if (evt.step === 'complete' && evt.data?.threats?.threats) threats.set(evt.data.threats.threats)
      },
      err => { failure = err },
      async () => {
        if (stopped) return
        pipelineRunning.set(false)
        // Keep `stop` registered until this finishes, so leaving the page
        // mid-refresh still sets `stopped` and nothing starts polling after.
        try {
          let refreshed
          try {
            refreshed = await getModel(id)
          } catch {
            if (!stopped) startPolling(id)
            return
          }
          if (stopped) return
          model = refreshed
          currentModel.set(refreshed)
          threats.set(refreshed.threats ?? [])
          if (refreshed.status !== 'in_progress') await loadSupplementary()
          else if (failure?.status === 404) interrupted = true
          else startPolling(id)
        } finally {
          if (stopFollowing === stop) stopFollowing = null
        }
      },
    )
    const stop = () => { stopped = true; stopFollowing = null; abort() }
    stopFollowing = stop
  }

  // Fallback when the live stream can't be followed (network error).
  function startPolling(id) {
    polling = true
    pollTimer = setInterval(async () => {
      try {
        const refreshed = await getModel(id)
        if (id !== params.id) return
        model = refreshed
        currentModel.set(model)
        threats.set(model.threats ?? [])
        if (refreshed.status === 'completed' || refreshed.status === 'failed') {
          stopPolling()
          await loadSupplementary()
        }
      } catch { /* ignore transient */ }
    }, 3000)
  }

  // Leaving the page only stops following the run; the run itself carries on.
  onDestroy(() => {
    stopPolling()
    if (stopFollowing) { stopFollowing(); pipelineRunning.set(false) }
    const abort = get(abortRun)
    if (abort) { abort(); abortRun.set(null) }
  })

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    polling = false
  }

  async function loadSupplementary() {
    const id = params.id
    const [a, f, tb, rawCounts, deps, dgs, mc] = await Promise.all([
      getModelAssets(params.id).catch(() => []),
      getModelFlows(params.id).catch(() => []),
      getModelTrustBoundaries(params.id).catch(() => []),
      getCommentCounts(params.id).catch(() => []),
      getModelDependencies(params.id).catch(() => []),
      listModelDiagrams(params.id).catch(() => []),
      getMaestroCoverage(params.id).catch(() => null),
    ])
    if (id !== params.id) return
    assets = a; flows = f; trustBoundaries = tb
    maestroCoverage = mc
    dependencyScans = deps
    diagrams = dgs
    selectedDiagramId = null
    diagramContentCache = {}
    diagramContentError = {}
    assetCommentCounts = {}
    flowCommentCounts = {}
    threatCommentCounts = {}
    for (const row of rawCounts) {
      if (!row.entity_type || !row.entity_id) continue
      if (row.entity_type === 'asset') assetCommentCounts[row.entity_id] = row.count
      else if (row.entity_type === 'flow') flowCommentCounts[row.entity_id] = row.count
      else if (row.entity_type === 'threat') threatCommentCounts[row.entity_id] = row.count
    }
  }

  const STATUS_CHIPS = {
    pending:     'chip-gray',
    in_progress: 'chip-blue',
    completed:   'chip-green',
    failed:      'chip-red',
    in_review:   'chip-amber',
    approved:    'chip-accent',
    archived:    'chip-gray',
  }

  // Manual review-workflow transitions surfaced as buttons. pending/in_progress/failed
  // are pipeline-driven and not user-selectable here.
  const STATUS_ACTIONS = {
    completed: [{ label: 'Send to review', to: 'in_review', primary: true }],
    in_review: [
      { label: 'Approve', to: 'approved', primary: true },
      { label: 'Back to completed', to: 'completed' },
      { label: 'Archive', to: 'archived' },
    ],
    approved: [{ label: 'Archive', to: 'archived' }],
  }
  // A viewer's re-run, context edit and status change get a 403, so hide them.
  $: canEdit = canEditProject($currentProject, $currentUser, model?.project_id)
  $: statusActions = canEdit ? (STATUS_ACTIONS[model?.status] ?? []) : []

  let changingStatus = false

  async function changeStatus(to) {
    changingStatus = true
    try {
      const updated = await updateModel(params.id, { status: to })
      model = updated
      currentModel.set(updated)
    } catch (err) {
      notify('error', `Status change failed: ${err.message}`)
    } finally {
      changingStatus = false
    }
  }

  async function selectDiagram(id) {
    selectedDiagramId = id
    const d = diagrams.find(x => x.id === id)
    // diagramFetchToken[id] being set means a fetch for this id is already in
    // flight (possibly started before a list reload) — don't start a second one.
    if (!d || d.kind === 'mermaid' || diagramContentCache[id] || diagramContentError[id] || diagramFetchToken[id] !== undefined) return
    const token = ++nextDiagramFetchToken
    diagramFetchToken = { ...diagramFetchToken, [id]: token }
    diagramContentLoading = { ...diagramContentLoading, [id]: true }
    try {
      const full = await getModelDiagram(params.id, id)
      if (diagramFetchToken[id] !== token) return // superseded — a newer fetch for this id owns the result now
      diagramContentCache = { ...diagramContentCache, [id]: full }
    } catch (err) {
      if (diagramFetchToken[id] !== token) return
      notify('error', `Failed to load diagram: ${err.message}`)
      diagramContentError = { ...diagramContentError, [id]: true }
    } finally {
      if (diagramFetchToken[id] === token) {
        const { [id]: _removedToken, ...restToken } = diagramFetchToken
        diagramFetchToken = restToken
        const { [id]: _removedLoading, ...restLoading } = diagramContentLoading
        diagramContentLoading = restLoading
      }
    }
  }

  function retryDiagram(id) {
    const { [id]: _removed, ...rest } = diagramContentError
    diagramContentError = rest
    selectDiagram(id)
  }

  function onTabKeydown(event, index) {
    if (diagrams.length < 2) return
    let next = null
    if (event.key === 'ArrowRight') next = (index + 1) % diagrams.length
    else if (event.key === 'ArrowLeft') next = (index - 1 + diagrams.length) % diagrams.length
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = diagrams.length - 1
    if (next !== null) {
      event.preventDefault()
      selectDiagram(diagrams[next].id)
      tabRefs[next]?.focus()
    }
  }

  /** The model's assumptions as a list (the API returns the stored JSON string). */
  function storedAssumptions(m) {
    const raw = m?.assumptions
    if (Array.isArray(raw)) return raw
    if (typeof raw !== 'string' || !raw.trim()) return []
    try {
      const parsed = JSON.parse(raw)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }

  function rerun() {
    const cfg = get(config)
    const provider = model?.provider ?? cfg?.default_provider
    const keyMissing = (
      (provider === 'anthropic' && cfg?.anthropic_api_key_set === false) ||
      (provider === 'openai' && cfg?.openai_api_key_set === false)
    )
    if (keyMissing) {
      notify('error', `No API key configured for ${provider}. Add one in Settings before re-running.`)
      return
    }
    const fd = new FormData()
    // The run route saves what it's sent over the stored assumptions, so send
    // them back (BB-82). has_ai_components is left out: the server reuses the
    // flag the model's last run stored. Dependencies are not re-sent (yet).
    fd.append('assumptions', JSON.stringify(storedAssumptions(model)))
    interrupted = false
    pipelineEvents.set([])
    pipelineRunning.set(true)
    threats.set([])
    const abort = subscribeToRun(
      params.id, fd,
      evt => {
        pipelineEvents.update(es => [...es, evt])
        if (evt.step === 'complete' && evt.data?.threats?.threats) threats.set(evt.data.threats.threats)
      },
      err => { notify('error', `Re-run error: ${err.message}`); pipelineRunning.set(false) },
      async () => {
        pipelineRunning.set(false)
        try {
          const refreshed = await getModel(params.id)
          model = refreshed; currentModel.set(refreshed); threats.set(refreshed.threats ?? [])
          await loadSupplementary()
        } catch { /* ignore */ }
      },
    )
    abortRun.set(abort)
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  {#if loading}
    <div class="flex justify-center py-20">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else if model}
    <!-- Header -->
    <!-- flex-wrap: the 642px button group plus even a short title is wider than the column
         at ~1024px; unwrapped, it widened the whole page (BB-28) -->
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-xl font-semibold text-c-text truncate">{model.title}</h1>
        <div class="flex items-center gap-2 mt-1">
          <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border capitalize {STATUS_CHIPS[model.status] ?? 'chip-gray'}">
            {model.status.replace('_', ' ')}
          </span>
          <span class="font-mono text-[11px] text-c-faint">{model.framework}</span>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-3">
        <Assignees modelId={params.id} projectId={model.project_id} />
        <ExportMenu modelId={params.id} />
        {#if canEdit}
          <a href="/models/{params.id}/context" use:link class="btn-ghost text-xs px-3 py-1.5">
            Edit Context
          </a>
        {/if}
        {#if canEdit && (model.status === 'completed' || model.status === 'failed' || interrupted)}
          <button type="button" on:click={rerun} disabled={$pipelineRunning}
            title="Re-run (description, assumptions and diagrams; dependencies need a new run)"
            class="btn-ghost text-xs px-3 py-1.5 disabled:opacity-50">
            Re-run
          </button>
        {/if}
        {#if model.status === 'completed'}
          <a href="/models/{params.id}/diff" use:link class="btn-ghost text-xs px-3 py-1.5">
            Compare
          </a>
        {/if}
        {#if model.status === 'completed'}
          <a href="/models/{params.id}/review" use:link class="btn-primary text-xs px-3 py-1.5">
            Review Threats
          </a>
        {/if}
        {#each statusActions as action (action.to)}
          <button type="button" on:click={() => changeStatus(action.to)} disabled={changingStatus}
            class="{action.primary ? 'btn-primary' : 'btn-ghost'} text-xs px-3 py-1.5 disabled:opacity-50">
            {action.label}
          </button>
        {/each}
      </div>
    </div>

    <!-- Polling banner -->
    {#if polling}
      <div class="card px-5 py-4 flex items-center gap-3 border-c-blue/30 bg-c-blue/5">
        <div class="w-4 h-4 border-2 border-c-blue border-t-transparent rounded-full animate-spin-slow flex-shrink-0"></div>
        <div>
          <p class="text-sm font-medium text-c-blue">Pipeline is running on the server</p>
          <p class="text-xs text-c-muted mt-0.5">Couldn't follow its live progress. Polling for completion every 3s…</p>
        </div>
      </div>
    {/if}

    {#if interrupted}
      <div class="card px-5 py-4 border-c-high/30 bg-c-high/5">
        <p class="text-sm font-medium text-c-high">This run was interrupted</p>
        <p class="text-xs text-c-muted mt-0.5">The server stopped before it finished, so it has no results. Re-run to try again.</p>
      </div>
    {/if}

    <!-- Pipeline progress -->
    {#if $pipelineRunning || $pipelineEvents.length > 0}
      <div class="card p-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Pipeline</h2>
        <PipelineProgress
          events={$pipelineEvents}
          running={$pipelineRunning}
          {stoppedReason}
          totalIterations={model.iteration_count ?? 3}
        />
        {#if !$pipelineRunning && $pipelineEvents.length > 0}
          <div class="mt-4 pt-4 border-t border-c-border flex gap-2">
            <a href="/models/{params.id}/review" use:link class="btn-primary text-sm px-4 py-2">
              Review {$threats.length} Threats
            </a>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Run summary: token usage by model, no prices (decided 2026-10-01) -->
    {#if runUsage?.by_model?.length}
      <div class="card p-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Run Summary</h2>
        <div class="space-y-1.5">
          {#each runUsage.by_model as m (m.model)}
            <div class="flex items-center justify-between text-xs">
              <span class="font-mono text-c-text2">{m.model}</span>
              <span class="font-mono text-c-muted">
                {m.total_tokens.toLocaleString()} tokens · {m.calls} call{m.calls === 1 ? '' : 's'}
              </span>
            </div>
          {/each}
        </div>
        <div class="mt-3 pt-3 border-t border-c-border flex items-center justify-between text-xs">
          <span class="text-c-muted">Total</span>
          <span class="font-mono font-semibold text-c-text2">{runUsage.total_tokens.toLocaleString()} tokens</span>
        </div>
        {#if runUsage.fast_model_share !== null && runUsage.fast_model_share !== undefined}
          <p class="text-[11px] text-c-faint mt-2">
            {Math.round(runUsage.fast_model_share * 100)}% of tokens served by {runUsage.fast_model}
          </p>
        {/if}
        {#if runUsage.fast_routing_disabled}
          <span class="inline-block mt-2 chip-amber font-mono text-[11px] px-2 py-0.5 rounded-chip">fast routing disabled mid-run</span>
        {/if}
        {#if runUsage.stopped_reason || guard}
          <div class="mt-3 pt-3 border-t border-c-border space-y-1 text-[11px]" data-testid="run-coverage">
            {#if runUsage.stopped_reason}
              <p class="text-c-muted">
                Stopped: <span class="font-mono text-c-text2">{STOP_LABELS[runUsage.stopped_reason] ?? runUsage.stopped_reason}</span>
              </p>
            {/if}
            {#if guard?.triggered}
              <p class="text-c-muted">
                Coverage guard overrode the stop at iteration {guard.iteration} for
                <span class="font-mono text-c-text2">{guard.targeted.join(', ')}</span>
              </p>
            {/if}
            {#if guard?.still_empty?.length}
              <p class="text-c-high">
                No LLM threats: <span class="font-mono">{guard.still_empty.join(', ')}</span>{guard.triggered ? ' after a targeted pass' : ''}
              </p>
            {/if}
            {#if naMaestro.length}
              <p class="text-c-muted">
                MAESTRO N/A (no matching component): <span class="font-mono">{naMaestro.join(', ')}</span>
              </p>
            {:else if guard?.unknown_maestro}
              <p class="text-c-muted">MAESTRO applicability not assessed (no component matched a rule)</p>
            {/if}
          </div>
        {/if}
        {#if stepRows.length}
          <details class="mt-3 pt-3 border-t border-c-border">
            <summary class="text-xs text-c-muted cursor-pointer select-none">By step ({stepRows.length})</summary>
            <div class="mt-2 overflow-x-auto">
              <table class="w-full text-[11px] font-mono">
                <thead>
                  <tr class="text-c-faint text-left">
                    <th class="font-normal py-1 pr-3">Step</th>
                    <th class="font-normal py-1 pr-3">Iter</th>
                    <th class="font-normal py-1 pr-3">Model</th>
                    <th class="font-normal py-1 pr-3 text-right">Input</th>
                    <th class="font-normal py-1 pr-3 text-right">Output</th>
                    <th class="font-normal py-1 pr-3 text-right">Cache read</th>
                    <th class="font-normal py-1 text-right">Cache write</th>
                  </tr>
                </thead>
                <tbody>
                  {#each stepRows as row, i (i)}
                    <tr class="border-t border-c-border {row.status === 'failed' ? 'text-c-critical' : 'text-c-text2'}">
                      <td class="py-1 pr-3">{row.step}</td>
                      <td class="py-1 pr-3 text-c-muted">{row.iteration}</td>
                      <td class="py-1 pr-3">
                        {row.model}
                        {#if runUsage.fast_model && row.model === runUsage.fast_model}
                          <span class="ml-1 chip-blue px-1.5 rounded-chip">fast</span>
                        {/if}
                      </td>
                      <td class="py-1 pr-3 text-right">{row.tokens.input_tokens.toLocaleString()}</td>
                      <td class="py-1 pr-3 text-right">{row.tokens.output_tokens.toLocaleString()}</td>
                      <td class="py-1 pr-3 text-right">{row.tokens.cache_read_tokens.toLocaleString()}</td>
                      <td class="py-1 text-right">{row.tokens.cache_write_tokens.toLocaleString()}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </details>
        {/if}
      </div>
    {/if}

    <!-- Code Analysis -->
    {#if codeAnalysis}
      <div class="card p-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">Code Analysis</h2>
        <div class="grid sm:grid-cols-2 gap-5">

          <div>
            <p class="text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-2">Tech Stack</p>
            {#if codeAnalysis.tech_stack?.length && codeAnalysis.tech_stack[0] !== 'Unknown'}
              <div class="flex flex-wrap gap-1.5">
                {#each codeAnalysis.tech_stack as tech}
                  <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-blue">{tech}</span>
                {/each}
              </div>
            {:else}
              <p class="text-xs text-c-faint italic">Not detected</p>
            {/if}
          </div>

          <div>
            <p class="text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-2">Auth Patterns</p>
            {#if codeAnalysis.auth_patterns?.length && codeAnalysis.auth_patterns[0] !== 'No auth patterns detected'}
              <div class="flex flex-wrap gap-1.5">
                {#each codeAnalysis.auth_patterns as a}
                  <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-accent">{a}</span>
                {/each}
              </div>
            {:else}
              <p class="text-xs text-c-faint italic">None detected</p>
            {/if}
          </div>

          <div>
            <p class="text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-2">Entry Points</p>
            {#if codeAnalysis.entry_points?.length && codeAnalysis.entry_points[0] !== 'No entry points detected'}
              <div class="space-y-0.5 max-h-28 overflow-y-auto">
                {#each codeAnalysis.entry_points as ep}
                  <div class="flex items-center gap-1.5 text-xs">
                    <span class="font-mono font-semibold flex-shrink-0 w-12 text-right
                      {ep.startsWith('POST') || ep.startsWith('PUT') || ep.startsWith('DELETE') || ep.startsWith('PATCH') ? 'text-c-high' : 'text-c-green'}">
                      {ep.split(' ')[0]}
                    </span>
                    <span class="font-mono text-c-text2">{ep.split(' ').slice(1).join(' ')}</span>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-xs text-c-faint italic">None detected</p>
            {/if}
          </div>

          <div>
            <p class="text-[10px] font-semibold text-c-faint uppercase tracking-wide mb-2">Security Observations</p>
            {#if codeAnalysis.security_observations?.length && codeAnalysis.security_observations[0] !== 'No security issues detected in automated scan'}
              <div class="space-y-1">
                {#each codeAnalysis.security_observations as obs}
                  <div class="flex items-start gap-1.5 text-xs">
                    <span class="flex-shrink-0 mt-0.5 {obs.startsWith('CRITICAL') ? 'text-c-critical' : 'text-c-high'}">⚠</span>
                    <span class="text-c-muted">{obs}</span>
                  </div>
                {/each}
              </div>
            {:else}
              <p class="text-xs text-c-faint italic">No issues flagged</p>
            {/if}
          </div>

        </div>
      </div>
    {/if}

    <!-- Diagram -->
    {#if !$pipelineRunning && diagrams.length > 0}
      <div class="card p-5">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">
            Diagram <span class="normal-case font-mono text-c-faint">({diagrams.length})</span>
          </h2>
          {#if diagrams.length > 1}
            <div role="tablist" aria-label="Diagrams" class="flex items-center gap-1.5 flex-wrap">
              {#each diagrams as d, i (d.id)}
                <button type="button" role="tab"
                  bind:this={tabRefs[i]}
                  id="diagram-tab-{d.id}"
                  aria-selected={d.id === (selectedDiagram?.id ?? null)}
                  aria-controls="diagram-panel"
                  tabindex={d.id === (selectedDiagram?.id ?? null) ? 0 : -1}
                  on:click={() => selectDiagram(d.id)}
                  on:keydown={(e) => onTabKeydown(e, i)}
                  class="font-mono text-[11px] px-2.5 py-1 rounded-chip border transition-colors
                    {d.id === (selectedDiagram?.id ?? null) ? 'chip-accent' : 'chip-gray'}">
                  {d.name}
                </button>
              {/each}
            </div>
          {/if}
        </div>
        <p class="text-xs text-c-faint mb-3">Re-runs reuse these diagrams. Upload new ones from a new run to replace them.</p>
        {#if selectedDiagram}
          <div id="diagram-panel" role="tabpanel"
            aria-labelledby={diagrams.length > 1 ? `diagram-tab-${selectedDiagram.id}` : undefined}>
            {#if selectedDiagram.kind !== 'mermaid' && diagramContentLoading[selectedDiagram.id] && !diagramContentCache[selectedDiagram.id]}
              <div class="flex justify-center py-12">
                <div class="w-5 h-5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
              </div>
            {:else if selectedDiagram.kind !== 'mermaid' && diagramContentError[selectedDiagram.id]}
              <div class="flex flex-col items-center gap-2 py-12">
                <p class="text-sm text-c-muted">Couldn't load diagram</p>
                <button type="button" class="btn-ghost text-xs px-3 py-1.5" on:click={() => retryDiagram(selectedDiagram.id)}>
                  Retry
                </button>
              </div>
            {:else}
              <DiagramView
                kind={selectedDiagram.kind}
                content={selectedDiagramContent ?? ''}
                mediaType={selectedDiagram.media_type}
                name={selectedDiagram.name}
              />
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Dependencies -->
    {#if !$pipelineRunning && dependencyScans.length > 0}
      <div class="card p-5">
        <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide mb-4">
          Dependencies <span class="normal-case font-mono text-c-faint">({dependencyScans.length})</span>
        </h2>
        <DependencyHeatmap scans={dependencyScans} />
      </div>
    {/if}

    <!-- MAESTRO coverage: MAESTRO/hybrid models, or any model that has MAESTRO threats -->
    {#if !$pipelineRunning && (['MAESTRO', 'HYBRID'].includes(model.framework) || maestroCoverage?.categories?.some((c) => c.status === 'covered'))}
      <MaestroCoverage coverage={maestroCoverage} />
    {/if}

    <!-- Gap analysis -->
    {#if !$pipelineRunning && model.status === 'completed'}
      {#if model.gap_summaries && model.gap_summaries.length > 0}
        <div class="card p-5">
          <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Iteration Gap Analysis</h2>
          <p class="text-xs text-c-faint mt-1 mb-4">Notes from the gap check after each pass. An entry before the last one identified missing coverage that fed into the next iteration; the final entry records why the run stopped.</p>
          {#each model.gap_summaries as gap, i}
            <div class="mt-3 pt-3 border-t border-c-border first:border-0 first:mt-0 first:pt-0">
              <p class="font-mono text-[11px] font-semibold text-c-accent uppercase tracking-wide">Iteration {i + 1}</p>
              <p class="text-sm text-c-text2 mt-1 whitespace-pre-line">{gap}</p>
            </div>
          {/each}
        </div>
      {:else if $threats.length > 0}
        <div class="card p-4">
          <!-- A rules-only run (provider offline) never reached gap analysis (BB-131). -->
          {#if runUsage?.stopped_reason === 'provider_offline'}
            <p class="text-xs text-c-faint">Gap analysis didn't run (rule engine only).</p>
          {:else}
            <p class="text-xs text-c-faint">Gap analysis: coverage was sufficient after iteration 1 — no gaps identified.</p>
          {/if}
        </div>
      {/if}
    {/if}

    <!-- Threat summary -->
    {#if $threats.length > 0 && !$pipelineRunning}
      <div class="card p-5">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">
            {$threats.length} Threats
          </h2>
          <a href="/models/{params.id}/review" use:link class="text-xs text-c-accent hover:underline">Review all →</a>
        </div>
        <div class="space-y-1">
          {#each $threats.slice(0, 5) as t}
            <div class="flex items-center gap-2 text-sm py-1.5 border-b border-c-divider last:border-0">
              <span class="text-c-faint flex-shrink-0">·</span>
              <span class="text-c-text2 truncate">{t.name}</span>
              <span class="ml-auto flex-shrink-0 font-mono text-[11px] text-c-faint">{t.stride_category ?? t.maestro_category ?? ''}</span>
            </div>
          {/each}
          {#if $threats.length > 5}
            <p class="text-xs text-c-faint pt-1">+{$threats.length - 5} more</p>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Assets / Flows / Trust Boundaries -->
    {#if !$pipelineRunning}
      <div class="grid sm:grid-cols-3 gap-4">
        <div class="card p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-[10px] font-semibold text-c-faint uppercase tracking-wide">
              Assets {#if assets.length > 0}<span class="normal-case font-mono text-c-muted">({assets.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => assetsList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-c-accent hover:text-c-accent/80 font-medium">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
              </svg>
              Add
            </button>
          </div>
          <ResourceList
            bind:this={assetsList}
            bind:items={assets}
            fields={[
              { key: 'name', label: 'Name' },
              { key: 'type', label: 'Type', type: 'select', options: ['Asset', 'Entity'], default: 'Asset', display: 'badge' },
              { key: 'description', label: 'Description', type: 'textarea', default: '' },
            ]}
            onCreate={(draft) => createAsset(params.id, draft)}
            onUpdate={(id, patch) => updateAsset(params.id, id, patch)}
            onDelete={(id) => deleteAsset(params.id, id)}
            emptyLabel="No assets yet."
          />
          <EntityComments items={assets} modelId={params.id} entityType="asset" commentCounts={assetCommentCounts} />
        </div>

        <div class="card p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-[10px] font-semibold text-c-faint uppercase tracking-wide">
              Data Flows {#if flows.length > 0}<span class="normal-case font-mono text-c-muted">({flows.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => flowsList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-c-accent hover:text-c-accent/80 font-medium">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
              </svg>
              Add
            </button>
          </div>
          <ResourceList
            bind:this={flowsList}
            bind:items={flows}
            fields={[
              { key: 'source_entity', label: 'Source', linkKey: 'source_asset_id' },
              { key: 'target_entity', label: 'Target', linkKey: 'target_asset_id' },
              { key: 'flow_description', label: 'Description', type: 'textarea', default: '' },
              { key: 'flow_type', label: 'Type', type: 'select', options: ['data', 'message', 'external', 'return'], default: 'data', display: 'badge' },
            ]}
            onCreate={(draft) => createFlow(params.id, draft)}
            onUpdate={(id, patch) => updateFlow(params.id, id, patch)}
            onDelete={(id) => deleteFlow(params.id, id)}
            emptyLabel="No data flows yet."
          />
          <EntityComments items={flows} modelId={params.id} entityType="flow" commentCounts={flowCommentCounts} />
        </div>

        <div class="card p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-[10px] font-semibold text-c-faint uppercase tracking-wide">
              Trust Boundaries {#if trustBoundaries.length > 0}<span class="normal-case font-mono text-c-muted">({trustBoundaries.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => boundariesList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-c-accent hover:text-c-accent/80 font-medium">
              <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
              </svg>
              Add
            </button>
          </div>
          <ResourceList
            bind:this={boundariesList}
            bind:items={trustBoundaries}
            fields={[
              { key: 'source_entity', label: 'Source', linkKey: 'source_asset_id' },
              { key: 'target_entity', label: 'Target', linkKey: 'target_asset_id' },
              { key: 'purpose', label: 'Purpose', type: 'textarea', default: '' },
            ]}
            onCreate={(draft) => createTrustBoundary(params.id, draft)}
            onUpdate={(id, patch) => updateTrustBoundary(params.id, id, patch)}
            onDelete={(id) => deleteTrustBoundary(params.id, id)}
            emptyLabel="No trust boundaries yet."
          />
        </div>
      </div>
    {/if}

    <Comments modelId={params.id} />
  {/if}
</div>
