<script>
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import { link } from 'svelte-spa-router'
  import {
    getModel, updateModel, getModelAssets, getModelFlows, getModelTrustBoundaries,
    createAsset, updateAsset, deleteAsset,
    createFlow, updateFlow, deleteFlow,
    createTrustBoundary, updateTrustBoundary, deleteTrustBoundary,
    subscribeToRun, getCommentCounts, getModelDependencies, listModelDiagrams, getModelDiagram,
  } from '../lib/api.js'
  import {
    currentModel, threats, pipelineEvents, pipelineRunning, abortRun, notify, config,
  } from '../lib/stores.js'
  import PipelineProgress from '../components/PipelineProgress.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'
  import ResourceList from '../components/ResourceList.svelte'
  import Assignees from '../components/Assignees.svelte'
  import Comments from '../components/Comments.svelte'
  import EntityComments from '../components/EntityComments.svelte'
  import DependencyHeatmap from '../components/DependencyHeatmap.svelte'
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
  let diagrams = []
  let selectedDiagramId = null
  let diagramContentCache = {} // { [diagramId]: { content, media_type } }
  let diagramContentLoading = false
  let tabRefs = []
  $: selectedDiagram = diagrams.find(d => d.id === selectedDiagramId) ?? diagrams[0] ?? null
  $: selectedDiagramContent = selectedDiagram
    ? (selectedDiagram.kind === 'mermaid'
        ? selectedDiagram.content
        : (diagramContentCache[selectedDiagram.id]?.content ?? null))
    : null
  // The default-selected diagram (page load, or after a list reload) also needs
  // its content lazily fetched, not just an explicit tab click.
  $: if (selectedDiagram && selectedDiagram.kind !== 'mermaid' && !diagramContentCache[selectedDiagram.id] && !diagramContentLoading) {
    selectDiagram(selectedDiagram.id)
  }
  /** @type {any} */ let assetsList
  /** @type {any} */ let flowsList
  /** @type {any} */ let boundariesList
  let loading = true
  let polling = false
  let pollTimer = null

  $: stoppedReason = $pipelineEvents.find(e => e.step === 'complete')?.data?.stopped_reason ?? ''
  $: codeAnalysis = $pipelineEvents.find(e => e.step === 'summarize_code' && e.status === 'completed')?.data?.code_summary ?? model?.code_summary ?? null
  // RunUsage from the COMPLETE event's data.usage (backend/models/usage.py) — tokens
  // by model and the fast-model share, no price fields (decided 2026-10-01). Falls
  // back to the persisted `usage` field (threat_models.usage_summary) since
  // pipelineEvents is cleared on mount unless a pipeline run is actively streaming
  // (see onMount), so a page reload after completion has no live SSE events.
  $: runUsage = $pipelineEvents.find(e => e.step === 'complete')?.data?.usage ?? model?.usage ?? null
  $: stepRows = (runUsage?.steps ?? []).map(s => ({ ...s, tokens: sumStepUsage(s.usage) }))

  // A step normally has one usage entry; a fast→main retry adds a second.
  function sumStepUsage(usage) {
    const t = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 }
    for (const u of usage ?? []) for (const k in t) t[k] += u[k] ?? 0
    return t
  }

  let _wasRunning = false
  $: {
    if (_wasRunning && !$pipelineRunning && model?.id === params.id) {
      loadSupplementary()
    }
    _wasRunning = $pipelineRunning
  }

  onMount(async () => {
    const alreadyRunning = get(pipelineRunning)
    if (!alreadyRunning) pipelineEvents.set([])
    try {
      model = await getModel(params.id)
      currentModel.set(model)
      threats.set(model.threats ?? [])
    } catch (err) {
      notify('error', `Failed to load model: ${err.message}`)
      loading = false
      return
    }
    loading = false
    if (alreadyRunning) return
    if (model.status === 'in_progress') {
      polling = true
      pollTimer = setInterval(async () => {
        try {
          const refreshed = await getModel(params.id)
          model = refreshed
          currentModel.set(model)
          threats.set(model.threats ?? [])
          if (refreshed.status === 'completed' || refreshed.status === 'failed') {
            stopPolling()
            await loadSupplementary()
          }
        } catch { /* ignore transient */ }
      }, 3000)
    } else if (model.status === 'completed' || model.status === 'failed') {
      await loadSupplementary()
    }
  })

  onDestroy(() => {
    stopPolling()
    const abort = get(abortRun)
    if (abort) { abort(); abortRun.set(null) }
  })

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    polling = false
  }

  async function loadSupplementary() {
    const [a, f, tb, rawCounts, deps, dgs] = await Promise.all([
      getModelAssets(params.id).catch(() => []),
      getModelFlows(params.id).catch(() => []),
      getModelTrustBoundaries(params.id).catch(() => []),
      getCommentCounts(params.id).catch(() => []),
      getModelDependencies(params.id).catch(() => []),
      listModelDiagrams(params.id).catch(() => []),
    ])
    assets = a; flows = f; trustBoundaries = tb
    dependencyScans = deps
    diagrams = dgs
    selectedDiagramId = null
    diagramContentCache = {}
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
  $: statusActions = STATUS_ACTIONS[model?.status] ?? []

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
    if (!d || d.kind === 'mermaid' || diagramContentCache[id]) return
    diagramContentLoading = true
    try {
      const full = await getModelDiagram(params.id, id)
      diagramContentCache = { ...diagramContentCache, [id]: full }
    } catch (err) {
      notify('error', `Failed to load diagram: ${err.message}`)
    } finally {
      diagramContentLoading = false
    }
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
    fd.append('assumptions', '[]')
    fd.append('has_ai_components', 'false')
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
    <div class="flex items-start justify-between gap-4">
      <div class="min-w-0">
        <h1 class="text-xl font-semibold text-c-text truncate">{model.title}</h1>
        <div class="flex items-center gap-2 mt-1">
          <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border capitalize {STATUS_CHIPS[model.status] ?? 'chip-gray'}">
            {model.status.replace('_', ' ')}
          </span>
          <span class="font-mono text-[11px] text-c-faint">{model.framework}</span>
        </div>
      </div>
      <div class="flex items-center gap-3 flex-shrink-0">
        <Assignees modelId={params.id} projectId={model.project_id} />
        <ExportMenu modelId={params.id} />
        <a href="/models/{params.id}/context" use:link class="btn-ghost text-xs px-3 py-1.5">
          Edit Context
        </a>
        {#if model.status === 'completed' || model.status === 'failed'}
          <button type="button" on:click={rerun} disabled={$pipelineRunning}
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
          <p class="text-xs text-c-muted mt-0.5">SSE stream lost on refresh. Polling for completion every 3s…</p>
        </div>
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
          <div id="diagram-panel" role="tabpanel" aria-labelledby="diagram-tab-{selectedDiagram.id}">
            {#if selectedDiagram.kind !== 'mermaid' && diagramContentLoading && !diagramContentCache[selectedDiagram.id]}
              <div class="flex justify-center py-12">
                <div class="w-5 h-5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
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

    <!-- Gap analysis -->
    {#if !$pipelineRunning && model.status === 'completed'}
      {#if model.gap_summaries && model.gap_summaries.length > 0}
        <div class="card p-5">
          <h2 class="text-xs font-semibold text-c-muted uppercase tracking-wide">Iteration Gap Analysis</h2>
          <p class="text-xs text-c-faint mt-1 mb-4">Each pass identified missing coverage that fed into the next iteration.</p>
          {#each model.gap_summaries as gap, i}
            <div class="mt-3 pt-3 border-t border-c-border first:border-0 first:mt-0 first:pt-0">
              <p class="font-mono text-[11px] font-semibold text-c-accent uppercase tracking-wide">Iteration {i + 1}</p>
              <p class="text-sm text-c-text2 mt-1 whitespace-pre-line">{gap}</p>
            </div>
          {/each}
        </div>
      {:else if $threats.length > 0}
        <div class="card p-4">
          <p class="text-xs text-c-faint">Gap analysis: coverage was sufficient after iteration 1 — no gaps identified.</p>
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
              { key: 'source_entity', label: 'Source' },
              { key: 'target_entity', label: 'Target' },
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
              { key: 'source_entity', label: 'Source' },
              { key: 'target_entity', label: 'Target' },
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
