<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { listModels, deleteModel } from '../lib/api.js'
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

  async function handleDelete(model, event) {
    event.stopPropagation()
    if (!confirm(`Delete "${model.title}"?\nThis removes all its threats, assets, flows, and trust boundaries.`)) return
    try {
      await deleteModel(model.id)
      models.update(ms => ms.filter(m => m.id !== model.id))
      notify('success', 'Threat model deleted.')
    } catch (err) {
      notify('error', `Delete failed: ${err.message}`)
    }
  }
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
        <div class="relative group">
          <a href="/models/{model.id}" use:link
            class="block bg-white rounded-xl border border-slate-200 p-5 hover:border-indigo-300 hover:shadow-sm transition-all">
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
          <button
            type="button"
            on:click={(e) => handleDelete(model, e)}
            title="Delete threat model"
            class="absolute top-2 right-2 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 transition-all">
            <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>
