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

  // Pending threats bucketed by severity for batch actions.
  // Severity prefers DREAD score (matches DreadBadge colour buckets:
  // <=3 low, <=6 medium, otherwise high). When DREAD is missing we
  // fall back to the `likelihood` field so rule-engine threats are
  // still classifiable.
  function severityOf(t) {
    const score = dreadScoreOf(t)
    if (score != null) {
      if (score >= 8) return 'critical'
      if (score > 6) return 'high'
      if (score >= 4) return 'medium'
      return 'low'
    }
    const l = String(t.likelihood ?? '').toLowerCase()
    if (l === 'critical') return 'critical'
    if (l === 'high') return 'high'
    if (l === 'medium' || l === 'med') return 'medium'
    if (l === 'low') return 'low'
    return 'unknown'
  }

  function dreadScoreOf(t) {
    if (t.dread_score != null) return Number(t.dread_score)
    if (t.dread?.damage != null) {
      const d = t.dread
      const vals = [d.damage, d.reproducibility, d.exploitability, d.affected_users, d.discoverability].filter(v => v != null)
      if (!vals.length) return null
      return vals.reduce((a, b) => a + b, 0) / vals.length
    }
    if (t.dread_damage != null) {
      const vals = [t.dread_damage, t.dread_reproducibility, t.dread_exploitability, t.dread_affected_users, t.dread_discoverability].filter(v => v != null)
      if (!vals.length) return null
      return vals.reduce((a, b) => a + b, 0) / vals.length
    }
    return null
  }

  $: criticalHighPending = pendingThreats.filter(t => {
    const s = severityOf(t)
    return s === 'critical' || s === 'high'
  })
  $: lowPending = pendingThreats.filter(t => severityOf(t) === 'low')

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
    await _bulkApply(pending, 'approved', `Approved ${pending.length} threats`, 'Bulk approve failed')
  }

  async function rejectAll() {
    const pending = $threats.filter(t => t.status === 'pending')
    await _bulkApply(pending, 'rejected', `Rejected ${pending.length} threats`, 'Bulk reject failed')
  }

  async function approveCriticalHigh() {
    const subset = criticalHighPending
    await _bulkApply(subset, 'approved', `Approved ${subset.length} Critical/High threats`, 'Bulk approve failed')
  }

  async function rejectLow() {
    const subset = lowPending
    await _bulkApply(subset, 'rejected', `Rejected ${subset.length} Low-severity threats`, 'Bulk reject failed')
  }

  async function _bulkApply(subset, nextStatus, successMsg, errMsg) {
    if (subset.length === 0) return
    const ids = new Set(subset.map(t => t.id))
    // Optimistic update — keep originals so we can revert on failure.
    const originals = $threats.filter(t => ids.has(t.id)).map(t => ({ id: t.id, status: t.status }))
    threats.update(ts => ts.map(t => ids.has(t.id) ? { ...t, status: nextStatus } : t))
    try {
      await Promise.all(subset.map(t => updateThreat(t.id, { status: nextStatus })))
      notify('success', successMsg)
    } catch (err) {
      // Revert the UI to the pre-action state so the display is internally
      // consistent. Note: some server calls in the Promise.all may already have
      // succeeded — the server state could be partially updated. The page will
      // re-sync on the next full load (navigate away and back).
      threats.update(ts => ts.map(t => {
        const orig = originals.find(o => o.id === t.id)
        return orig ? { ...t, status: orig.status } : t
      }))
      notify('error', `${errMsg}: ${err.message}. Reload the page to see the latest server state.`)
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
      <div class="flex items-center gap-3 flex-wrap justify-end">
        {#if criticalHighPending.length > 0}
          <button
            type="button"
            on:click={approveCriticalHigh}
            class="text-sm font-medium text-green-700 hover:text-green-800"
            title="Approve all pending threats with DREAD score >6 or High/Critical likelihood">
            Approve Critical+High ({criticalHighPending.length})
          </button>
        {/if}
        {#if lowPending.length > 0}
          <button
            type="button"
            on:click={rejectLow}
            class="text-sm font-medium text-amber-700 hover:text-amber-800"
            title="Reject all pending threats with DREAD score &lt;4 or Low likelihood">
            Reject Low ({lowPending.length})
          </button>
        {/if}
        <button
          type="button"
          on:click={approveAll}
          class="text-sm font-medium text-green-700 hover:text-green-800">
          Approve all ({pendingThreats.length})
        </button>
        <button
          type="button"
          on:click={rejectAll}
          class="text-sm font-medium text-red-700 hover:text-red-800">
          Reject all ({pendingThreats.length})
        </button>
      </div>
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
        <ThreatCard
          {threat}
          readonly={false}
          on:approve={handleApprove}
          on:reject={handleReject}
          on:dread-updated={e => threats.update(ts => ts.map(t => t.id === e.detail.id ? { ...t, ...e.detail } : t))} />
      {/each}
    </div>
  {/if}
</div>
