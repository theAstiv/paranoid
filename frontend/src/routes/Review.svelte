<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getModelThreats, updateThreat } from '../lib/api.js'
  import { threats, currentModel, notify } from '../lib/stores.js'
  import ThreatCard from '../components/ThreatCard.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'

  /** @type {{ id: string }} */
  export let params = {}

  let loading = true
  let filter = 'all'

  const FILTERS = ['all', 'pending', 'approved', 'rejected']

  $: filtered = filter === 'all' ? $threats : $threats.filter(t => t.status === filter)
  $: pendingThreats = $threats.filter(t => t.status === 'pending')

  onMount(async () => {
    try {
      const data = await getModelThreats(params.id)
      threats.set(data)
    } catch (err) {
      notify('error', `Failed to load threats: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function handleApprove(evt) {
    const threat = evt.detail
    threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: 'approved' } : t))
    try {
      await updateThreat(threat.id, { status: 'approved' })
    } catch (err) {
      // Revert on failure
      threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: threat.status } : t))
      notify('error', `Failed to approve: ${err.message}`)
    }
  }

  async function handleReject(evt) {
    const threat = evt.detail
    threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: 'rejected' } : t))
    try {
      await updateThreat(threat.id, { status: 'rejected' })
    } catch (err) {
      threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: threat.status } : t))
      notify('error', `Failed to reject: ${err.message}`)
    }
  }

  async function approveAll() {
    const pending = $threats.filter(t => t.status === 'pending')
    threats.update(ts => ts.map(t => t.status === 'pending' ? { ...t, status: 'approved' } : t))
    try {
      await Promise.all(pending.map(t => updateThreat(t.id, { status: 'approved' })))
      notify('success', `Approved ${pending.length} threats`)
    } catch (err) {
      notify('error', `Bulk approve failed: ${err.message}`)
    }
  }
</script>

<div class="max-w-4xl mx-auto space-y-5">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-2xl font-semibold text-slate-900">Review Threats</h1>
      {#if $currentModel}
        <p class="text-sm text-slate-500 mt-0.5">{$currentModel.title}</p>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <ExportMenu modelId={params.id} />
      <a href="/models/{params.id}" use:link class="text-sm text-slate-500 hover:text-slate-700">← Results</a>
    </div>
  </div>

  <!-- Filters + bulk actions -->
  <div class="flex items-center justify-between">
    <div class="flex gap-1">
      {#each FILTERS as f}
        <button
          type="button"
          on:click={() => filter = f}
          class="px-3 py-1 text-sm rounded-md capitalize {filter === f ? 'bg-indigo-600 text-white' : 'text-slate-600 hover:bg-slate-100'}">
          {f}
          {#if f === 'all'}
            ({$threats.length})
          {:else if f === 'pending'}
            ({pendingThreats.length})
          {:else}
            ({$threats.filter(t => t.status === f).length})
          {/if}
        </button>
      {/each}
    </div>
    {#if pendingThreats.length > 0}
      <button
        type="button"
        on:click={approveAll}
        class="text-sm font-medium text-green-700 hover:text-green-800">
        Approve all pending ({pendingThreats.length})
      </button>
    {/if}
  </div>

  <!-- Threat list -->
  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  {:else if filtered.length === 0}
    <div class="text-center py-12 text-slate-400">
      No {filter === 'all' ? '' : filter} threats.
    </div>
  {:else}
    <div class="space-y-4">
      {#each filtered as threat (threat.id)}
        <ThreatCard {threat} readonly={false} on:approve={handleApprove} on:reject={handleReject} />
      {/each}
    </div>
  {/if}
</div>
