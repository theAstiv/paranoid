<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { listModels, getModelThreats } from '../lib/api.js'
  import { notify } from '../lib/stores.js'
  import ThreatCard from '../components/ThreatCard.svelte'

  let models = []
  let loadedThreats = {}  // modelId → threat[]
  let loading = true
  let expandedModel = null
  let loadingThreats = false

  // Filters
  let searchQuery = ''
  let filterImpact = ''
  let filterStatus = ''

  const IMPACTS = ['', 'Low', 'Medium', 'High', 'Critical']
  const STATUSES = ['', 'pending', 'approved', 'rejected', 'mitigated']

  $: currentThreats = expandedModel ? (loadedThreats[expandedModel] ?? []) : []
  $: filtered = currentThreats.filter(t => {
    const q = searchQuery.toLowerCase()
    if (q && !t.name?.toLowerCase().includes(q) && !t.description?.toLowerCase().includes(q)) return false
    if (filterImpact && t.impact !== filterImpact) return false
    if (filterStatus && t.status !== filterStatus) return false
    return true
  })

  onMount(async () => {
    try {
      models = await listModels({ limit: 50 })
    } catch (err) {
      notify('error', `Failed to load models: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function toggleModel(id) {
    if (expandedModel === id) { expandedModel = null; return }
    expandedModel = id
    if (!loadedThreats[id]) {
      loadingThreats = true
      try {
        loadedThreats[id] = await getModelThreats(id)
        loadedThreats = loadedThreats  // trigger reactivity
      } catch (err) {
        notify('error', `Failed to load threats: ${err.message}`)
      } finally {
        loadingThreats = false
      }
    }
  }
</script>

<div class="max-w-4xl mx-auto space-y-5">
  <h1 class="text-2xl font-semibold text-slate-900">Threat Library</h1>

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if models.length === 0}
    <div class="text-center py-12 text-slate-400">No threat models yet.</div>
  {:else}
    <!-- Model list -->
    <div class="space-y-2">
      {#each models as m (m.id)}
        <div class="bg-white rounded-xl border {expandedModel === m.id ? 'border-indigo-300' : 'border-slate-200'} overflow-hidden">
          <button
            type="button"
            on:click={() => toggleModel(m.id)}
            class="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors">
            <div class="flex items-center gap-3">
              <span class="font-medium text-slate-900">{m.title}</span>
              <span class="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600">{m.framework}</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-slate-400">
              {#if m.threat_count != null}
                <span>{m.threat_count} threats</span>
              {/if}
              <svg class="w-4 h-4 transition-transform {expandedModel === m.id ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </div>
          </button>

          {#if expandedModel === m.id}
            <div class="border-t border-slate-100 p-4 space-y-4">
              <!-- Filters -->
              <div class="flex flex-wrap gap-2">
                <input
                  type="text"
                  bind:value={searchQuery}
                  placeholder="Search threats…"
                  class="flex-1 min-w-40 rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500"
                />
                <select bind:value={filterImpact} class="rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500">
                  {#each IMPACTS as imp}
                    <option value={imp}>{imp || 'Any impact'}</option>
                  {/each}
                </select>
                <select bind:value={filterStatus} class="rounded-md border-slate-300 text-sm focus:border-indigo-500 focus:ring-indigo-500">
                  {#each STATUSES as s}
                    <option value={s}>{s || 'Any status'}</option>
                  {/each}
                </select>
              </div>

              {#if loadingThreats}
                <div class="flex justify-center py-8">
                  <div class="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
                </div>
              {:else if filtered.length === 0}
                <p class="text-sm text-slate-400 text-center py-6">No threats match the current filters.</p>
              {:else}
                <div class="space-y-3">
                  {#each filtered as t (t.id)}
                    <ThreatCard threat={t} readonly={true} />
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
