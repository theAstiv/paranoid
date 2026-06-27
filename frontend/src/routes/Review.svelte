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

  $: criticalHighPending = pendingThreats.filter(t => { const s = severityOf(t); return s === 'critical' || s === 'high' })
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
    await _bulkApply(criticalHighPending, 'approved', `Approved ${criticalHighPending.length} Critical/High threats`, 'Bulk approve failed')
  }

  async function rejectLow() {
    await _bulkApply(lowPending, 'rejected', `Rejected ${lowPending.length} Low-severity threats`, 'Bulk reject failed')
  }

  async function _bulkApply(subset, nextStatus, successMsg, errMsg) {
    if (subset.length === 0) return
    const ids = new Set(subset.map(t => t.id))
    const originals = $threats.filter(t => ids.has(t.id)).map(t => ({ id: t.id, status: t.status }))
    threats.update(ts => ts.map(t => ids.has(t.id) ? { ...t, status: nextStatus } : t))
    try {
      await Promise.all(subset.map(t => updateThreat(t.id, { status: nextStatus })))
      notify('success', successMsg)
    } catch (err) {
      threats.update(ts => ts.map(t => {
        const orig = originals.find(o => o.id === t.id)
        return orig ? { ...t, status: orig.status } : t
      }))
      notify('error', `${errMsg}: ${err.message}. Reload the page to see the latest server state.`)
    }
  }
</script>

<div class="max-w-[920px] mx-auto space-y-5">
  <!-- Header -->
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-xl font-semibold text-c-text">Review Threats</h1>
      {#if $currentModel}
        <p class="text-sm text-c-muted mt-0.5">{$currentModel.title}</p>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <ExportMenu modelId={params.id} />
      <a href="/models/{params.id}" use:link class="text-sm text-c-muted hover:text-c-text2">← Results</a>
    </div>
  </div>

  <!-- Filters + bulk actions -->
  <div class="flex items-center justify-between gap-4 flex-wrap">
    <div class="flex gap-1">
      {#each FILTERS as f}
        <button
          type="button"
          on:click={() => filter = f}
          class="px-3 py-1 text-sm rounded-panel capitalize transition-colors
            {filter === f ? 'bg-c-accent text-[#04141A] font-medium' : 'text-c-muted hover:bg-c-well hover:text-c-text2'}">
          {f}
          <span class="font-mono text-[11px] ml-0.5">
            {#if f === 'all'}({$threats.length}){:else if f === 'pending'}({pendingThreats.length}){:else}({$threats.filter(t => t.status === f).length}){/if}
          </span>
        </button>
      {/each}
    </div>
    {#if pendingThreats.length > 0}
      <div class="flex items-center gap-3 flex-wrap">
        {#if criticalHighPending.length > 0}
          <button type="button" on:click={approveCriticalHigh}
            class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors"
            title="Approve all pending threats with DREAD score >6 or High/Critical likelihood">
            Approve Critical+High ({criticalHighPending.length})
          </button>
        {/if}
        {#if lowPending.length > 0}
          <button type="button" on:click={rejectLow}
            class="text-xs font-medium text-c-high hover:text-c-high/80 transition-colors"
            title="Reject all pending threats with DREAD score <4 or Low likelihood">
            Reject Low ({lowPending.length})
          </button>
        {/if}
        <button type="button" on:click={approveAll}
          class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors">
          Approve all ({pendingThreats.length})
        </button>
        <button type="button" on:click={rejectAll}
          class="text-xs font-medium text-c-critical hover:text-c-critical/80 transition-colors">
          Reject all ({pendingThreats.length})
        </button>
      </div>
    {/if}
  </div>

  <!-- Threat list -->
  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else if filtered.length === 0}
    <div class="text-center py-12 text-c-faint text-sm">
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
