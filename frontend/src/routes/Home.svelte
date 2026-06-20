<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { listModels, deleteModel } from '../lib/api.js'
  import { models, notify } from '../lib/stores.js'
  import ModelCard from '../components/ModelCard.svelte'

  let loading = true

  // Filter state
  let filterStatus = ''
  let filterFramework = ''

  const STATUS_FILTERS = ['pending', 'in_progress', 'completed', 'failed', 'in_review', 'approved']
  const FRAMEWORK_FILTERS = ['STRIDE', 'MAESTRO', 'HYBRID']

  $: filtered = $models.filter(m => {
    if (filterStatus && m.status !== filterStatus) return false
    if (filterFramework && m.framework !== filterFramework) return false
    return true
  })

  async function handleDelete(model) {
    if (!confirm(`Delete "${model.title}"?\nThis removes all its threats, assets, flows, and trust boundaries.`)) return
    try {
      await deleteModel(model.id)
      models.update(ms => ms.filter(m => m.id !== model.id))
      notify('success', 'Threat model deleted.')
    } catch (err) {
      notify('error', `Delete failed: ${err.message}`)
    }
  }

  onMount(async () => {
    try {
      const data = await listModels({ limit: 50 })
      models.set(data)
    } catch (err) {
      notify('error', `Failed to load models: ${err.message}`)
    } finally {
      loading = false
    }
  })
</script>

<div class="max-w-[1120px] mx-auto">
  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <div>
      <p class="font-mono text-[10px] tracking-[1px] text-c-faint uppercase mb-1">Threat Models</p>
      <h1 class="text-c-text text-xl font-semibold">
        {loading ? '' : `${$models.length} model${$models.length !== 1 ? 's' : ''}`}
      </h1>
    </div>
    <a href="/models/new" use:link class="btn-primary">
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
      </svg>
      New Model
    </a>
  </div>

  <!-- Filter chips -->
  {#if !loading && $models.length > 0}
    <div class="flex items-center gap-2 flex-wrap mb-6">
      <!-- Status filters -->
      {#each STATUS_FILTERS as s}
        {@const active = filterStatus === s}
        {@const count = $models.filter(m => m.status === s).length}
        {#if count > 0}
          <button
            type="button"
            on:click={() => filterStatus = active ? '' : s}
            class="font-mono text-[11px] px-2.5 py-1 rounded-chip border transition-all
                   {active
                     ? 'bg-c-accent/20 text-c-accent border-c-accent/40'
                     : 'bg-c-panel border-c-border text-c-muted hover:border-c-border-strong hover:text-c-text3'}"
          >
            {s.replace(/_/g, ' ')}
            <span class="ml-1 opacity-60">{count}</span>
          </button>
        {/if}
      {/each}

      <!-- Framework filters -->
      {#each FRAMEWORK_FILTERS as fw}
        {@const active = filterFramework === fw}
        {@const count = $models.filter(m => m.framework === fw).length}
        {#if count > 0}
          <button
            type="button"
            on:click={() => filterFramework = active ? '' : fw}
            class="font-mono text-[11px] px-2.5 py-1 rounded-chip border transition-all
                   {active
                     ? 'bg-c-blue/20 text-c-blue border-c-blue/40'
                     : 'bg-c-panel border-c-border text-c-muted hover:border-c-border-strong hover:text-c-text3'}"
          >
            {fw}
            <span class="ml-1 opacity-60">{count}</span>
          </button>
        {/if}
      {/each}

      <!-- Clear filters -->
      {#if filterStatus || filterFramework}
        <button
          type="button"
          on:click={() => { filterStatus = ''; filterFramework = '' }}
          class="font-mono text-[11px] px-2 py-1 rounded-chip text-c-faint hover:text-c-muted transition-colors"
        >
          clear ×
        </button>
      {/if}
    </div>
  {/if}

  <!-- Body -->
  {#if loading}
    <div class="flex justify-center py-24">
      <div class="w-5 h-5 rounded-full border-2 border-c-accent border-t-transparent animate-spin-slow"></div>
    </div>

  {:else if $models.length === 0}
    <!-- Empty state -->
    <div class="flex flex-col items-center justify-center py-24 border border-dashed border-c-border rounded-card">
      <svg class="w-10 h-10 text-c-faint mb-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <p class="text-c-muted text-sm mb-4">No threat models yet.</p>
      <a href="/models/new" use:link class="btn-primary">
        Create your first model
      </a>
    </div>

  {:else if filtered.length === 0}
    <!-- Filter empty state -->
    <div class="flex flex-col items-center justify-center py-16 border border-dashed border-c-border rounded-card">
      <p class="text-c-muted text-sm mb-2">No models match the current filters.</p>
      <button
        type="button"
        on:click={() => { filterStatus = ''; filterFramework = '' }}
        class="font-mono text-[12px] text-c-faint hover:text-c-accent transition-colors"
      >
        Clear filters
      </button>
    </div>

  {:else}
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each filtered as model (model.id)}
        <ModelCard
          {model}
          onDelete={() => handleDelete(model)}
        />
      {/each}
    </div>
  {/if}
</div>
