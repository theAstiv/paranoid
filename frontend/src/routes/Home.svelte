<script>
  import { onMount } from 'svelte'
  import { link, push } from 'svelte-spa-router'
  import { listModels } from '../lib/api.js'
  import { models, notify } from '../lib/stores.js'

  let loading = true

  const statusColors = {
    pending: 'bg-slate-100 text-slate-600',
    in_progress: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
  }

  const frameworkColors = {
    STRIDE: 'bg-indigo-100 text-indigo-700',
    MAESTRO: 'bg-teal-100 text-teal-700',
    HYBRID: 'bg-violet-100 text-violet-700',
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
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

<div>
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-semibold text-slate-900">Threat Models</h1>
    <a href="/models/new" use:link
      class="inline-flex items-center gap-1.5 bg-indigo-600 text-white text-sm px-4 py-2 rounded-md hover:bg-indigo-700 transition-colors">
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/></svg>
      New Model
    </a>
  </div>

  {#if loading}
    <div class="flex justify-center py-20">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if $models.length === 0}
    <div class="text-center py-20 border-2 border-dashed border-slate-200 rounded-xl">
      <svg class="mx-auto w-12 h-12 text-slate-300 mb-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      </svg>
      <p class="text-slate-500 mb-4">No threat models yet.</p>
      <a href="/models/new" use:link
        class="inline-flex items-center gap-1.5 bg-indigo-600 text-white text-sm px-4 py-2 rounded-md hover:bg-indigo-700 transition-colors">
        Create your first model
      </a>
    </div>
  {:else}
    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each $models as model (model.id)}
        <a href="/models/{model.id}" use:link
          class="block bg-white rounded-xl border border-slate-200 p-5 hover:border-indigo-300 hover:shadow-sm transition-all group">
          <div class="flex items-start justify-between mb-3">
            <h2 class="font-medium text-slate-900 group-hover:text-indigo-700 line-clamp-2 flex-1 pr-2">
              {model.title}
            </h2>
            <span class="flex-shrink-0 text-xs px-2 py-0.5 rounded-full font-medium {frameworkColors[model.framework] ?? 'bg-slate-100 text-slate-600'}">
              {model.framework}
            </span>
          </div>
          <div class="flex items-center justify-between text-xs text-slate-500">
            <span class="px-2 py-0.5 rounded-full {statusColors[model.status] ?? 'bg-slate-100 text-slate-600'}">
              {model.status.replace('_', ' ')}
            </span>
            <div class="flex items-center gap-3">
              {#if model.threat_count != null}
                <span>{model.threat_count} threats</span>
              {/if}
              <span>{formatDate(model.created_at)}</span>
            </div>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</div>
