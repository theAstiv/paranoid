<script>
  import { onMount, onDestroy } from 'svelte'
  import { get } from 'svelte/store'
  import { link } from 'svelte-spa-router'
  import {
    getModel, getModelAssets, getModelFlows, getModelTrustBoundaries,
    createAsset, updateAsset, deleteAsset,
    createFlow, updateFlow, deleteFlow,
    createTrustBoundary, updateTrustBoundary, deleteTrustBoundary,
  } from '../lib/api.js'
  import {
    currentModel, threats, pipelineEvents, pipelineRunning, abortRun, notify,
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

  // Detect when SSE stream finishes (pipelineRunning goes true → false) and load
  // supplementary data that onDone in NewModel.svelte cannot access.
  let _wasRunning = false
  $: {
    if (_wasRunning && !$pipelineRunning && model?.id === params.id) {
      loadSupplementary()
    }
    _wasRunning = $pipelineRunning
  }

  onMount(async () => {
    const alreadyRunning = get(pipelineRunning)

    // Only clear events when we're not mid-stream from NewModel
    if (!alreadyRunning) {
      pipelineEvents.set([])
    }

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

    if (alreadyRunning) {
      // Stream started in NewModel before navigation — stores are already updating.
      // Nothing to do; PipelineProgress renders from $pipelineEvents.
      return
    }

    if (model.status === 'in_progress') {
      // User refreshed mid-run: SSE stream is gone, pipeline is still running on the server.
      // Poll the model endpoint every 3s until it reaches a terminal state.
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
        } catch { /* ignore transient poll errors */ }
      }, 3000)
    } else if (model.status === 'completed' || model.status === 'failed') {
      await loadSupplementary()
    }
    // status === 'pending': model was created but /run was never called.
    // This shouldn't happen in normal flow (NewModel starts the run before
    // navigating), but we show the model header without auto-triggering.
  })

  onDestroy(() => {
    stopPolling()
    // Abort the SSE stream when navigating away; clear the stored reference
    const abort = get(abortRun)
    if (abort) {
      abort()
      abortRun.set(null)
    }
  })

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    polling = false
  }

  async function loadSupplementary() {
    const [a, f, tb] = await Promise.all([
      getModelAssets(params.id).catch(() => []),
      getModelFlows(params.id).catch(() => []),
      getModelTrustBoundaries(params.id).catch(() => []),
    ])
    assets = a
    flows = f
    trustBoundaries = tb
  }

  const statusColors = {
    pending: 'bg-slate-100 text-slate-600',
    in_progress: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }
</script>

<div class="max-w-4xl mx-auto space-y-6">
  {#if loading}
    <div class="flex justify-center py-20">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if model}
    <!-- Header -->
    <div class="flex items-start justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{model.title}</h1>
        <div class="flex items-center gap-2 mt-1">
          <span class="text-xs px-2 py-0.5 rounded-full font-medium {statusColors[model.status] ?? 'bg-slate-100 text-slate-600'}">
            {model.status.replace('_', ' ')}
          </span>
          <span class="text-xs text-slate-400">{model.framework}</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <ExportMenu modelId={params.id} />
        {#if model.status === 'completed'}
          <a href="/models/{params.id}/review" use:link
            class="px-3 py-1.5 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors">
            Review Threats
          </a>
        {/if}
      </div>
    </div>

    <!-- Polling banner (shown after page refresh mid-run) -->
    {#if polling}
      <div class="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-center gap-3">
        <div class="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0"></div>
        <div>
          <p class="text-sm font-medium text-blue-800">Pipeline is running on the server</p>
          <p class="text-xs text-blue-600 mt-0.5">The SSE stream was lost on refresh. Polling for completion every 3 s…</p>
        </div>
      </div>
    {/if}

    <!-- Pipeline progress (shown while streaming or when events exist from this session) -->
    {#if $pipelineRunning || $pipelineEvents.length > 0}
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <h2 class="text-sm font-semibold text-slate-700 mb-4">Pipeline</h2>
        <PipelineProgress
          events={$pipelineEvents}
          running={$pipelineRunning}
          {stoppedReason}
          totalIterations={model.iteration_count ?? 3}
        />
        {#if !$pipelineRunning && $pipelineEvents.length > 0}
          <div class="mt-4 pt-4 border-t border-slate-100 flex gap-2">
            <a href="/models/{params.id}/review" use:link
              class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors">
              Review {$threats.length} Threats
            </a>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Threat summary (after run completes) -->
    {#if $threats.length > 0 && !$pipelineRunning}
      <div class="bg-white rounded-xl border border-slate-200 p-5">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold text-slate-700">{$threats.length} Threats</h2>
          <a href="/models/{params.id}/review" use:link class="text-xs text-indigo-600 hover:underline">Review all →</a>
        </div>
        <div class="space-y-1">
          {#each $threats.slice(0, 5) as t}
            <div class="flex items-center gap-2 text-sm py-1 border-b border-slate-50">
              <span class="text-xs font-mono text-slate-400 flex-shrink-0 w-4">·</span>
              <span class="text-slate-800 truncate">{t.name}</span>
              <span class="ml-auto flex-shrink-0 text-xs text-slate-400">{t.stride_category ?? t.maestro_category ?? ''}</span>
            </div>
          {/each}
          {#if $threats.length > 5}
            <p class="text-xs text-slate-400 pt-1">+{$threats.length - 5} more</p>
          {/if}
        </div>
      </div>
    {/if}

    <!-- Assets / Flows / Trust Boundaries (always visible, CRUD-enabled) -->
    {#if !$pipelineRunning}
      <div class="grid sm:grid-cols-3 gap-4">
        <!-- Assets -->
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Assets {#if assets.length > 0}<span class="normal-case font-normal">({assets.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => assetsList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium">
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

        <!-- Data Flows -->
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Data Flows {#if flows.length > 0}<span class="normal-case font-normal">({flows.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => flowsList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium">
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

        <!-- Trust Boundaries -->
        <div class="bg-white rounded-xl border border-slate-200 p-4">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Trust Boundaries {#if trustBoundaries.length > 0}<span class="normal-case font-normal">({trustBoundaries.length})</span>{/if}
            </h3>
            <button type="button" on:click={() => boundariesList.startAdd()}
              class="flex items-center gap-0.5 text-xs text-indigo-600 hover:text-indigo-800 font-medium">
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
