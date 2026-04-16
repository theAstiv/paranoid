<script>
  import { onDestroy, onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import {
    getModelAssets, getModelFlows, getModelTrustBoundaries, getModel,
    createAsset, updateAsset, deleteAsset,
    createFlow, updateFlow, deleteFlow,
    createTrustBoundary, updateTrustBoundary, deleteTrustBoundary,
    subscribeToExtract,
  } from '../lib/api.js'
  import { notify } from '../lib/stores.js'

  /** @type {{ id: string }} */
  export let params = {}

  let model = null
  let assets = []
  let flows = []
  let boundaries = []
  let loading = true
  let extracting = false
  let extractLog = []
  let abortExtract = null

  onDestroy(() => abortExtract?.())

  // ── Load ────────────────────────────────────────────────────────────────────

  onMount(async () => {
    try {
      const [m, a, f, b] = await Promise.all([
        getModel(params.id),
        getModelAssets(params.id),
        getModelFlows(params.id),
        getModelTrustBoundaries(params.id),
      ])
      model = m
      assets = a
      flows = f
      boundaries = b
    } catch (e) {
      notify('error', `Failed to load context: ${e.message}`)
    } finally {
      loading = false
    }
  })

  async function reload() {
    const [a, f, b] = await Promise.all([
      getModelAssets(params.id),
      getModelFlows(params.id),
      getModelTrustBoundaries(params.id),
    ])
    assets = a
    flows = f
    boundaries = b
  }

  // ── Extract from description ────────────────────────────────────────────────

  function runExtract() {
    extracting = true
    extractLog = []
    abortExtract = subscribeToExtract(
      params.id,
      evt => { extractLog = [...extractLog, evt] },
      err => { notify('error', `Extraction failed: ${err.message}`); extracting = false },
      async () => {
        extracting = false
        abortExtract = null
        await reload()
        notify('success', 'Context extracted successfully')
      },
    )
  }

  // ── Asset editing ────────────────────────────────────────────────────────────

  let editingAsset = null  // asset id being edited
  let assetDraft = {}

  function startEditAsset(a) {
    editingAsset = a.id
    assetDraft = { name: a.name, description: a.description, type: a.type }
  }

  async function saveAsset(a) {
    try {
      await updateAsset(params.id, a.id, assetDraft)
      assets = assets.map(x => x.id === a.id ? { ...x, ...assetDraft } : x)
      editingAsset = null
    } catch (e) { notify('error', `Save failed: ${e.message}`) }
  }

  async function removeAsset(id) {
    try {
      await deleteAsset(params.id, id)
      assets = assets.filter(a => a.id !== id)
    } catch (e) { notify('error', `Delete failed: ${e.message}`) }
  }

  let addingAsset = false
  let newAsset = { name: '', description: '', type: 'Asset' }

  async function submitNewAsset() {
    if (!newAsset.name.trim()) return
    try {
      const created = await createAsset(params.id, newAsset)
      assets = [...assets, created]
      addingAsset = false
      newAsset = { name: '', description: '', type: 'Asset' }
    } catch (e) { notify('error', `Create failed: ${e.message}`) }
  }

  // ── Flow editing ─────────────────────────────────────────────────────────────

  let editingFlow = null
  let flowDraft = {}

  function startEditFlow(f) {
    editingFlow = f.id
    flowDraft = { source_entity: f.source_entity, target_entity: f.target_entity, flow_description: f.flow_description, flow_type: f.flow_type }
  }

  async function saveFlow(f) {
    try {
      await updateFlow(params.id, f.id, flowDraft)
      flows = flows.map(x => x.id === f.id ? { ...x, ...flowDraft } : x)
      editingFlow = null
    } catch (e) { notify('error', `Save failed: ${e.message}`) }
  }

  async function removeFlow(id) {
    try {
      await deleteFlow(params.id, id)
      flows = flows.filter(f => f.id !== id)
    } catch (e) { notify('error', `Delete failed: ${e.message}`) }
  }

  let addingFlow = false
  let newFlow = { source_entity: '', target_entity: '', flow_description: '', flow_type: 'data' }

  async function submitNewFlow() {
    if (!newFlow.source_entity.trim() || !newFlow.target_entity.trim()) return
    try {
      const created = await createFlow(params.id, newFlow)
      flows = [...flows, created]
      addingFlow = false
      newFlow = { source_entity: '', target_entity: '', flow_description: '', flow_type: 'data' }
    } catch (e) { notify('error', `Create failed: ${e.message}`) }
  }

  // ── Trust boundary editing ────────────────────────────────────────────────────

  let editingBoundary = null
  let boundaryDraft = {}

  function startEditBoundary(b) {
    editingBoundary = b.id
    boundaryDraft = { source_entity: b.source_entity, target_entity: b.target_entity, purpose: b.purpose }
  }

  async function saveBoundary(b) {
    try {
      await updateTrustBoundary(params.id, b.id, boundaryDraft)
      boundaries = boundaries.map(x => x.id === b.id ? { ...x, ...boundaryDraft } : x)
      editingBoundary = null
    } catch (e) { notify('error', `Save failed: ${e.message}`) }
  }

  async function removeBoundary(id) {
    try {
      await deleteTrustBoundary(params.id, id)
      boundaries = boundaries.filter(b => b.id !== id)
    } catch (e) { notify('error', `Delete failed: ${e.message}`) }
  }

  let addingBoundary = false
  let newBoundary = { source_entity: '', target_entity: '', purpose: '' }

  async function submitNewBoundary() {
    if (!newBoundary.source_entity.trim() || !newBoundary.target_entity.trim()) return
    try {
      const created = await createTrustBoundary(params.id, newBoundary)
      boundaries = [...boundaries, created]
      addingBoundary = false
      newBoundary = { source_entity: '', target_entity: '', purpose: '' }
    } catch (e) { notify('error', `Create failed: ${e.message}`) }
  }
</script>

{#if loading}
  <div class="flex justify-center py-20"><div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div></div>
{:else}
<div class="space-y-8">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <div class="flex items-center gap-2 text-sm text-slate-400 mb-1">
        <a href={`/models/${params.id}`} use:link class="hover:text-slate-600">Results</a>
        <span>/</span>
        <span class="text-slate-600">Review Context</span>
      </div>
      <h1 class="text-2xl font-semibold text-slate-900">{model?.title ?? 'Review Context'}</h1>
      <p class="text-sm text-slate-500 mt-0.5">Review and edit extracted assets, flows, and trust boundaries before re-running the pipeline.</p>
    </div>
    <div class="flex gap-3">
      <button
        type="button"
        on:click={runExtract}
        disabled={extracting}
        class="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 disabled:opacity-50 transition-colors">
        {#if extracting}
          <div class="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
          Extracting…
        {:else}
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>
          Re-extract from description
        {/if}
      </button>
      <a href={`/models/${params.id}/review`} use:link
        class="px-4 py-2 text-sm font-medium text-indigo-600 border border-indigo-200 rounded-md hover:bg-indigo-50 transition-colors">
        Go to Review →
      </a>
    </div>
  </div>

  <!-- Extract log (shown while running) -->
  {#if extractLog.length > 0}
    <div class="bg-slate-900 rounded-lg p-3 text-xs font-mono text-slate-300 space-y-0.5 max-h-32 overflow-y-auto">
      {#each extractLog as evt}
        <div class="opacity-80">[{evt.step}] {evt.message ?? ''}</div>
      {/each}
    </div>
  {/if}

  <!-- Assets -->
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-base font-semibold text-slate-800">Assets & Entities <span class="text-slate-400 font-normal text-sm">({assets.length})</span></h2>
      <button type="button" on:click={() => { addingAsset = true }}
        class="text-xs text-indigo-600 hover:underline">+ Add asset</button>
    </div>

    {#each assets as a (a.id)}
      <div class="bg-white rounded-lg border border-slate-200 p-3">
        {#if editingAsset === a.id}
          <div class="space-y-2">
            <div class="flex gap-2">
              <input type="text" bind:value={assetDraft.name} placeholder="Name"
                class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
              <select bind:value={assetDraft.type}
                class="border border-slate-300 rounded px-2 py-1 text-sm">
                <option>Asset</option><option>Entity</option>
              </select>
            </div>
            <input type="text" bind:value={assetDraft.description} placeholder="Description"
              class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
            <div class="flex gap-2">
              <button type="button" on:click={() => saveAsset(a)}
                class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Save</button>
              <button type="button" on:click={() => editingAsset = null}
                class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
            </div>
          </div>
        {:else}
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <span class="text-xs px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 font-medium mr-2">{a.type}</span>
              <span class="text-sm font-medium text-slate-900">{a.name}</span>
              {#if a.description}
                <p class="text-xs text-slate-500 mt-0.5 truncate">{a.description}</p>
              {/if}
            </div>
            <div class="flex gap-1.5 flex-shrink-0">
              <button type="button" on:click={() => startEditAsset(a)}
                class="text-slate-400 hover:text-indigo-600 p-1 rounded hover:bg-indigo-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
              </button>
              <button type="button" on:click={() => removeAsset(a.id)}
                class="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-red-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
              </button>
            </div>
          </div>
        {/if}
      </div>
    {/each}

    {#if addingAsset}
      <div class="bg-slate-50 rounded-lg border border-dashed border-slate-300 p-3 space-y-2">
        <div class="flex gap-2">
          <input type="text" bind:value={newAsset.name} placeholder="Name *"
            class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
          <select bind:value={newAsset.type}
            class="border border-slate-300 rounded px-2 py-1 text-sm">
            <option>Asset</option><option>Entity</option>
          </select>
        </div>
        <input type="text" bind:value={newAsset.description} placeholder="Description"
          class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
        <div class="flex gap-2">
          <button type="button" on:click={submitNewAsset}
            class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Add</button>
          <button type="button" on:click={() => { addingAsset = false; newAsset = { name: '', description: '', type: 'Asset' } }}
            class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
        </div>
      </div>
    {/if}
  </section>

  <!-- Data Flows -->
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-base font-semibold text-slate-800">Data Flows <span class="text-slate-400 font-normal text-sm">({flows.length})</span></h2>
      <button type="button" on:click={() => { addingFlow = true }}
        class="text-xs text-indigo-600 hover:underline">+ Add flow</button>
    </div>

    {#each flows as f (f.id)}
      <div class="bg-white rounded-lg border border-slate-200 p-3">
        {#if editingFlow === f.id}
          <div class="space-y-2">
            <div class="flex gap-2">
              <input type="text" bind:value={flowDraft.source_entity} placeholder="Source"
                class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
              <span class="text-slate-400 self-center">→</span>
              <input type="text" bind:value={flowDraft.target_entity} placeholder="Target"
                class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
            </div>
            <input type="text" bind:value={flowDraft.flow_description} placeholder="Description"
              class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
            <div class="flex gap-2">
              <button type="button" on:click={() => saveFlow(f)}
                class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Save</button>
              <button type="button" on:click={() => editingFlow = null}
                class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
            </div>
          </div>
        {:else}
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-900">
                <span class="text-slate-700">{f.source_entity}</span>
                <span class="text-slate-400 mx-1.5">→</span>
                <span class="text-slate-700">{f.target_entity}</span>
              </div>
              {#if f.flow_description}
                <p class="text-xs text-slate-500 mt-0.5 truncate">{f.flow_description}</p>
              {/if}
            </div>
            <div class="flex gap-1.5 flex-shrink-0">
              <button type="button" on:click={() => startEditFlow(f)}
                class="text-slate-400 hover:text-indigo-600 p-1 rounded hover:bg-indigo-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
              </button>
              <button type="button" on:click={() => removeFlow(f.id)}
                class="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-red-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
              </button>
            </div>
          </div>
        {/if}
      </div>
    {/each}

    {#if addingFlow}
      <div class="bg-slate-50 rounded-lg border border-dashed border-slate-300 p-3 space-y-2">
        <div class="flex gap-2">
          <input type="text" bind:value={newFlow.source_entity} placeholder="Source *"
            class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
          <span class="text-slate-400 self-center">→</span>
          <input type="text" bind:value={newFlow.target_entity} placeholder="Target *"
            class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
        </div>
        <input type="text" bind:value={newFlow.flow_description} placeholder="Description"
          class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
        <div class="flex gap-2">
          <button type="button" on:click={submitNewFlow}
            class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Add</button>
          <button type="button" on:click={() => { addingFlow = false; newFlow = { source_entity: '', target_entity: '', flow_description: '', flow_type: 'data' } }}
            class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
        </div>
      </div>
    {/if}
  </section>

  <!-- Trust Boundaries -->
  <section class="space-y-3">
    <div class="flex items-center justify-between">
      <h2 class="text-base font-semibold text-slate-800">Trust Boundaries <span class="text-slate-400 font-normal text-sm">({boundaries.length})</span></h2>
      <button type="button" on:click={() => { addingBoundary = true }}
        class="text-xs text-indigo-600 hover:underline">+ Add boundary</button>
    </div>

    {#each boundaries as b (b.id)}
      <div class="bg-white rounded-lg border border-slate-200 p-3">
        {#if editingBoundary === b.id}
          <div class="space-y-2">
            <div class="flex gap-2">
              <input type="text" bind:value={boundaryDraft.source_entity} placeholder="Source"
                class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
              <span class="text-slate-400 self-center">/</span>
              <input type="text" bind:value={boundaryDraft.target_entity} placeholder="Target"
                class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
            </div>
            <input type="text" bind:value={boundaryDraft.purpose} placeholder="Purpose"
              class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
            <div class="flex gap-2">
              <button type="button" on:click={() => saveBoundary(b)}
                class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Save</button>
              <button type="button" on:click={() => editingBoundary = null}
                class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
            </div>
          </div>
        {:else}
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-medium text-slate-900">
                <span class="text-slate-700">{b.source_entity}</span>
                <span class="text-slate-400 mx-1.5">↔</span>
                <span class="text-slate-700">{b.target_entity}</span>
              </div>
              {#if b.purpose}
                <p class="text-xs text-slate-500 mt-0.5 truncate">{b.purpose}</p>
              {/if}
            </div>
            <div class="flex gap-1.5 flex-shrink-0">
              <button type="button" on:click={() => startEditBoundary(b)}
                class="text-slate-400 hover:text-indigo-600 p-1 rounded hover:bg-indigo-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/></svg>
              </button>
              <button type="button" on:click={() => removeBoundary(b.id)}
                class="text-slate-400 hover:text-red-500 p-1 rounded hover:bg-red-50">
                <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
              </button>
            </div>
          </div>
        {/if}
      </div>
    {/each}

    {#if addingBoundary}
      <div class="bg-slate-50 rounded-lg border border-dashed border-slate-300 p-3 space-y-2">
        <div class="flex gap-2">
          <input type="text" bind:value={newBoundary.source_entity} placeholder="Source *"
            class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
          <span class="text-slate-400 self-center">↔</span>
          <input type="text" bind:value={newBoundary.target_entity} placeholder="Target *"
            class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm" />
        </div>
        <input type="text" bind:value={newBoundary.purpose} placeholder="Purpose"
          class="w-full border border-slate-300 rounded px-2 py-1 text-sm" />
        <div class="flex gap-2">
          <button type="button" on:click={submitNewBoundary}
            class="px-3 py-1 text-xs font-medium text-white bg-indigo-600 rounded hover:bg-indigo-700">Add</button>
          <button type="button" on:click={() => { addingBoundary = false; newBoundary = { source_entity: '', target_entity: '', purpose: '' } }}
            class="px-3 py-1 text-xs font-medium text-slate-600 bg-slate-100 rounded hover:bg-slate-200">Cancel</button>
        </div>
      </div>
    {/if}
  </section>
</div>
{/if}
