<script>
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import { link } from 'svelte-spa-router'
  import {
    getModel, getModelAssets, getModelFlows, getModelTrustBoundaries,
    createAsset, updateAsset, deleteAsset,
    createFlow, updateFlow, deleteFlow,
    createTrustBoundary, updateTrustBoundary, deleteTrustBoundary,
    subscribeToRun,
  } from '../lib/api.js'
  import {
    currentModel, threats, pipelineEvents, pipelineRunning, abortRun, notify, config,
  } from '../lib/stores.js'
  import PipelineProgress from '../components/PipelineProgress.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'
  import ResourceList from '../components/ResourceList.svelte'

  /** @type {{ id: string }} */
  export let params = {}

  let model = null
  let assets = []
  let flows = []
  let trustBoundaries = []
  /** @type {any} */ let assetsList
  /** @type {any} */ let flowsList
  /** @type {any} */ let boundariesList
  let loading = true
  let polling = false
  let pollTimer = null

  $: stoppedReason = $pipelineEvents.find(e => e.step === 'complete')?.data?.stopped_reason ?? ''
  $: codeAnalysis = $pipelineEvents.find(e => e.step === 'summarize_code' && e.status === 'completed')?.data?.code_summary ?? model?.code_summary ?? null

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
    const [a, f, tb] = await Promise.all([
      getModelAssets(params.id).catch(() => []),
      getModelFlows(params.id).catch(() => []),
      getModelTrustBoundaries(params.id).catch(() => []),
    ])
    assets = a; flows = f; trustBoundaries = tb
  }

  const STATUS_CHIPS = {
    pending:     'chip-gray',
    in_progress: 'chip-blue',
    completed:   'chip-green',
    failed:      'chip-red',
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
      <div class="flex items-center gap-2 flex-shrink-0">
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
          <a href="/models/{params.id}/review" use:link class="btn-primary text-xs px-3 py-1.5">
            Review Threats
          </a>
        {/if}
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
  {/if}
</div>
