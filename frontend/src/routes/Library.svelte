<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { listModels, getModelThreats, deleteModel } from '../lib/api.js'
  import { notify } from '../lib/stores.js'
  import ThreatCard from '../components/ThreatCard.svelte'

  let models = []
  let loadedThreats = {}
  let loading = true
  let expandedModel = null
  let loadingThreats = false

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
        loadedThreats = loadedThreats
      } catch (err) {
        notify('error', `Failed to load threats: ${err.message}`)
      } finally {
        loadingThreats = false
      }
    }
  }

  async function handleDelete(id, title, event) {
    event.stopPropagation()
    if (!confirm(`Delete threat model "${title}"?\nThis removes all its threats, assets, flows, and trust boundaries.`)) return
    try {
      await deleteModel(id)
      models = models.filter(m => m.id !== id)
      if (expandedModel === id) expandedModel = null
      delete loadedThreats[id]
      notify('success', 'Threat model deleted.')
    } catch (err) {
      notify('error', `Delete failed: ${err.message}`)
    }
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <h1 class="text-xl font-semibold text-c-text">Threat Library</h1>

  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else if models.length === 0}
    <div class="text-center py-12 text-c-faint text-sm">No threat models yet.</div>
  {:else}
    <div class="space-y-2">
      {#each models as m (m.id)}
        <div class="card overflow-hidden transition-colors
          {expandedModel === m.id ? 'border-c-accent/40' : ''}">
          <button
            type="button"
            on:click={() => toggleModel(m.id)}
            class="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-c-well/60 transition-colors">
            <div class="flex items-center gap-3 min-w-0">
              <span class="font-medium text-c-text2 truncate">{m.title}</span>
              <span class="font-mono text-[11px] px-2 py-0.5 rounded-chip border chip-accent flex-shrink-0">{m.framework}</span>
            </div>
            <div class="flex items-center gap-3 text-xs text-c-faint flex-shrink-0">
              {#if m.threat_count != null}
                <span class="font-mono">{m.threat_count} threats</span>
              {/if}
              <button
                type="button"
                on:click={(e) => handleDelete(m.id, m.title, e)}
                on:keydown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleDelete(m.id, m.title, e) }}
                title="Delete threat model"
                class="p-1 rounded hover:bg-c-critical/10 hover:text-c-critical transition-colors">
                <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                </svg>
              </button>
              <svg class="w-4 h-4 transition-transform {expandedModel === m.id ? 'rotate-180' : ''}" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </div>
          </button>

          {#if expandedModel === m.id}
            <div class="border-t border-c-border p-4 space-y-4 bg-c-well/30">
              <!-- Filters -->
              <div class="flex flex-wrap gap-2">
                <input
                  type="text"
                  bind:value={searchQuery}
                  placeholder="Search threats…"
                  aria-label="Search threats"
                  class="flex-1 min-w-40 field text-sm"
                />
                <select bind:value={filterImpact} aria-label="Filter by impact" class="field text-sm">
                  {#each IMPACTS as imp}
                    <option value={imp}>{imp || 'Any impact'}</option>
                  {/each}
                </select>
                <select bind:value={filterStatus} aria-label="Filter by status" class="field text-sm">
                  {#each STATUSES as s}
                    <option value={s}>{s || 'Any status'}</option>
                  {/each}
                </select>
              </div>

              {#if loadingThreats}
                <div class="flex justify-center py-8">
                  <div class="w-5 h-5 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
                </div>
              {:else if filtered.length === 0}
                <p class="text-sm text-c-faint text-center py-6">No threats match the current filters.</p>
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
