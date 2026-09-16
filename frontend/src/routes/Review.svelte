<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getModelThreats, updateThreat, bulkUpdateThreatStatus, getCommentCounts } from '../lib/api.js'
  import { threats, currentModel, notify } from '../lib/stores.js'
  import ThreatCard from '../components/ThreatCard.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'

  /** @type {{ id: string }} */
  export let params = {}

  let loading = true
  let filter = 'all'
  let sortBy = 'default'
  let sourceFilter = 'all'
  let selectedCategories = []
  let dreadMin = 0
  let dreadMax = 10
  let confMin = 0
  let confMax = 100
  let showFilters = false

  /** @type {Set<string>} */
  let selectedIds = new Set()
  let bulkBusy = false
  let commentCounts = {}

  const STATUS_FILTERS = ['all', 'pending', 'approved', 'rejected']

  const STRIDE_CATEGORIES = [
    'Spoofing', 'Tampering', 'Repudiation',
    'Information Disclosure', 'Denial of Service', 'Elevation of Privilege'
  ]

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

  // Filter chain — clear selection when filters change so users never act on hidden threats
  $: statusFiltered = filter === 'all' ? $threats : $threats.filter(t => t.status === filter)
  $: categoryFiltered = selectedCategories.length === 0
    ? statusFiltered
    : statusFiltered.filter(t => selectedCategories.includes(t.stride_category))
  $: sourceFiltered = sourceFilter === 'all'
    ? categoryFiltered
    : categoryFiltered.filter(t => t.source === sourceFilter)
  $: dreadFiltered = sourceFiltered.filter(t => {
    const s = dreadScoreOf(t)
    return s == null || (s >= dreadMin && s <= dreadMax)
  })
  $: confFiltered = dreadFiltered.filter(t => {
    if (t.confidence == null) return true
    const pct = Math.round(t.confidence * 100)
    return pct >= confMin && pct <= confMax
  })

  // Sort
  $: filtered = sortThreats(confFiltered, sortBy)

  // Prune selectedIds to only contain threats visible after filtering
  $: {
    const visibleIds = new Set(filtered.map(t => t.id))
    const pruned = new Set([...selectedIds].filter(id => visibleIds.has(id)))
    if (pruned.size !== selectedIds.size) {
      selectedIds = pruned
    }
  }

  function sortThreats(list, by) {
    if (by === 'default') return list
    const copy = [...list]
    if (by === 'dread') {
      copy.sort((a, b) => (dreadScoreOf(b) ?? -1) - (dreadScoreOf(a) ?? -1))
    } else if (by === 'confidence') {
      copy.sort((a, b) => (b.confidence ?? -1) - (a.confidence ?? -1))
    } else if (by === 'category') {
      copy.sort((a, b) => (a.stride_category ?? '').localeCompare(b.stride_category ?? ''))
    }
    return copy
  }

  $: pendingThreats = $threats.filter(t => t.status === 'pending')
  $: criticalHighPending = pendingThreats.filter(t => { const s = severityOf(t); return s === 'critical' || s === 'high' })
  $: lowPending = pendingThreats.filter(t => severityOf(t) === 'low')
  $: selectedCount = selectedIds.size
  $: allFilteredSelected = filtered.length > 0 && filtered.every(t => selectedIds.has(t.id))

  onMount(async () => {
    try {
      const [data, rawCounts] = await Promise.all([
        getModelThreats(params.id),
        getCommentCounts(params.id).catch(() => []),
      ])
      threats.set(data)
      for (const row of rawCounts) {
        if (row.entity_type === 'threat' && row.entity_id) {
          commentCounts[row.entity_id] = row.count
        }
      }
      commentCounts = commentCounts
    } catch (err) {
      notify('error', `Failed to load threats: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function handleApprove(threat) {
    threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: 'approved' } : t))
    try {
      await updateThreat(threat.id, { status: 'approved' })
    } catch (err) {
      threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: threat.status } : t))
      notify('error', `Failed to approve: ${err.message}`)
    }
  }

  async function handleReject(threat) {
    threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: 'rejected' } : t))
    try {
      await updateThreat(threat.id, { status: 'rejected' })
    } catch (err) {
      threats.update(ts => ts.map(t => t.id === threat.id ? { ...t, status: threat.status } : t))
      notify('error', `Failed to reject: ${err.message}`)
    }
  }

  function handleToggleSelect(threat) {
    const next = new Set(selectedIds)
    if (next.has(threat.id)) {
      next.delete(threat.id)
    } else {
      next.add(threat.id)
    }
    selectedIds = next
  }

  function toggleSelectAll() {
    if (allFilteredSelected) {
      selectedIds = new Set()
    } else {
      selectedIds = new Set(filtered.map(t => t.id))
    }
  }

  async function bulkAction(status) {
    const ids = [...selectedIds]
    if (ids.length === 0) return
    bulkBusy = true
    const originals = $threats.filter(t => selectedIds.has(t.id)).map(t => ({ id: t.id, status: t.status }))
    threats.update(ts => ts.map(t => selectedIds.has(t.id) ? { ...t, status } : t))
    try {
      const result = await bulkUpdateThreatStatus(ids, status)
      notify('success', `${result.updated} threats ${status}`)
      selectedIds = new Set()
    } catch (err) {
      threats.update(ts => ts.map(t => {
        const orig = originals.find(o => o.id === t.id)
        return orig ? { ...t, status: orig.status } : t
      }))
      notify('error', `Bulk ${status} failed: ${err.message}`)
    } finally {
      bulkBusy = false
    }
  }

  /**
   * Apply a bulk status change to an explicit list of threat IDs.
   * Used by the convenience buttons (approve all, reject low, etc.).
   */
  async function bulkActionFor(threatList, status, label) {
    const ids = threatList.map(t => t.id)
    if (ids.length === 0) return
    bulkBusy = true
    const idSet = new Set(ids)
    const originals = threatList.map(t => ({ id: t.id, status: t.status }))
    threats.update(ts => ts.map(t => idSet.has(t.id) ? { ...t, status } : t))
    try {
      const result = await bulkUpdateThreatStatus(ids, status)
      notify('success', `${label}: ${result.updated} threats`)
    } catch (err) {
      threats.update(ts => ts.map(t => {
        const orig = originals.find(o => o.id === t.id)
        return orig ? { ...t, status: orig.status } : t
      }))
      notify('error', `${label} failed: ${err.message}`)
    } finally {
      bulkBusy = false
    }
  }

  function toggleCategory(cat) {
    if (selectedCategories.includes(cat)) {
      selectedCategories = selectedCategories.filter(c => c !== cat)
    } else {
      selectedCategories = [...selectedCategories, cat]
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

  <!-- Status filters + bulk actions -->
  <div class="flex items-center justify-between gap-4 flex-wrap">
    <div class="flex gap-1">
      {#each STATUS_FILTERS as f}
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
    <div class="flex items-center gap-3 flex-wrap">
      <button type="button" on:click={() => showFilters = !showFilters}
        class="text-xs font-medium text-c-accent hover:text-c-accent/80 transition-colors">
        {showFilters ? 'Hide filters' : 'Filters'}
      </button>
      {#if pendingThreats.length > 0}
        {#if criticalHighPending.length > 0}
          <button type="button" on:click={() => bulkActionFor(criticalHighPending, 'approved', 'Approved Critical/High')} disabled={bulkBusy}
            class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors disabled:opacity-50">
            Approve Critical+High ({criticalHighPending.length})
          </button>
        {/if}
        {#if lowPending.length > 0}
          <button type="button" on:click={() => bulkActionFor(lowPending, 'rejected', 'Rejected Low')} disabled={bulkBusy}
            class="text-xs font-medium text-c-high hover:text-c-high/80 transition-colors disabled:opacity-50">
            Reject Low ({lowPending.length})
          </button>
        {/if}
        <button type="button" on:click={() => bulkActionFor(pendingThreats, 'approved', 'Approved all')} disabled={bulkBusy}
          class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors disabled:opacity-50">
          Approve all ({pendingThreats.length})
        </button>
        <button type="button" on:click={() => bulkActionFor(pendingThreats, 'rejected', 'Rejected all')} disabled={bulkBusy}
          class="text-xs font-medium text-c-critical hover:text-c-critical/80 transition-colors disabled:opacity-50">
          Reject all ({pendingThreats.length})
        </button>
      {/if}
    </div>
  </div>

  <!-- Advanced filters -->
  {#if showFilters}
    <div class="bg-c-well border border-c-border rounded-panel p-4 space-y-3">
      <div class="flex flex-wrap gap-4">
        <!-- STRIDE category -->
        <div class="space-y-1">
          <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">STRIDE Category</p>
          <div class="flex flex-wrap gap-1">
            {#each STRIDE_CATEGORIES as cat}
              <button type="button" on:click={() => toggleCategory(cat)}
                class="px-2 py-0.5 text-[11px] font-mono rounded-chip border transition-colors
                  {selectedCategories.includes(cat) ? 'chip-accent' : 'chip-gray'}">
                {cat}
              </button>
            {/each}
          </div>
        </div>

        <!-- Source -->
        <div class="space-y-1">
          <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">Source</p>
          <div class="flex gap-1">
            {#each [['all', 'All'], ['llm', 'LLM'], ['rule_engine', 'Rule Engine']] as [val, label]}
              <button type="button" on:click={() => sourceFilter = val}
                class="px-2 py-0.5 text-[11px] font-mono rounded-chip border transition-colors
                  {sourceFilter === val ? 'chip-accent' : 'chip-gray'}">
                {label}
              </button>
            {/each}
          </div>
        </div>

        <!-- Sort -->
        <div class="space-y-1">
          <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">Sort by</p>
          <select bind:value={sortBy}
            class="text-xs bg-c-input border border-c-border rounded px-2 py-1 text-c-text focus:outline-none focus:border-c-accent">
            <option value="default">Default</option>
            <option value="dread">DREAD score</option>
            <option value="confidence">Confidence</option>
            <option value="category">Category</option>
          </select>
        </div>
      </div>

      <div class="flex flex-wrap gap-6">
        <!-- DREAD range -->
        <div class="space-y-1">
          <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">DREAD range</p>
          <div class="flex items-center gap-2">
            <input type="number" min="0" max="10" step="0.5" bind:value={dreadMin}
              class="w-14 bg-c-input border border-c-border rounded px-1.5 py-0.5 text-xs font-mono text-c-text text-right focus:outline-none focus:border-c-accent" />
            <span class="text-c-faint text-xs">–</span>
            <input type="number" min="0" max="10" step="0.5" bind:value={dreadMax}
              class="w-14 bg-c-input border border-c-border rounded px-1.5 py-0.5 text-xs font-mono text-c-text text-right focus:outline-none focus:border-c-accent" />
          </div>
        </div>

        <!-- Confidence range -->
        <div class="space-y-1">
          <p class="font-mono text-[10px] font-semibold text-c-muted uppercase tracking-wide">Confidence %</p>
          <div class="flex items-center gap-2">
            <input type="number" min="0" max="100" step="5" bind:value={confMin}
              class="w-14 bg-c-input border border-c-border rounded px-1.5 py-0.5 text-xs font-mono text-c-text text-right focus:outline-none focus:border-c-accent" />
            <span class="text-c-faint text-xs">–</span>
            <input type="number" min="0" max="100" step="5" bind:value={confMax}
              class="w-14 bg-c-input border border-c-border rounded px-1.5 py-0.5 text-xs font-mono text-c-text text-right focus:outline-none focus:border-c-accent" />
          </div>
        </div>
      </div>
    </div>
  {/if}

  <!-- Selection bar -->
  {#if selectedCount > 0}
    <div class="flex items-center gap-3 bg-c-accent/10 border border-c-accent/30 rounded-panel px-4 py-2">
      <span class="text-xs font-medium text-c-text">{selectedCount} of {filtered.length} selected</span>
      <button type="button" on:click={() => bulkAction('approved')} disabled={bulkBusy}
        class="btn-primary text-xs px-3 py-1 disabled:opacity-50">
        Approve selected ({selectedCount})
      </button>
      <button type="button" on:click={() => bulkAction('rejected')} disabled={bulkBusy}
        class="btn-ghost text-xs px-3 py-1 disabled:opacity-50">
        Reject selected ({selectedCount})
      </button>
      <button type="button" on:click={() => selectedIds = new Set()}
        class="ml-auto text-xs text-c-faint hover:text-c-text2 transition-colors">
        Clear selection
      </button>
    </div>
  {/if}

  <!-- Threat list -->
  {#if loading}
    <div class="flex justify-center py-16">
      <div class="w-6 h-6 border-2 border-c-accent border-t-transparent rounded-full animate-spin-slow"></div>
    </div>
  {:else if filtered.length === 0}
    <div class="text-center py-12 text-c-faint text-sm">
      No {filter === 'all' ? '' : filter} threats{selectedCategories.length > 0 || sourceFilter !== 'all' ? ' matching filters' : ''}.
    </div>
  {:else}
    <div class="flex items-center justify-between mb-2">
      <label class="flex items-center gap-2 text-xs text-c-muted cursor-pointer">
        <input type="checkbox" checked={allFilteredSelected} on:change={toggleSelectAll}
          class="w-3.5 h-3.5 rounded border-c-border-strong text-c-accent focus:ring-c-accent/30" />
        Select all ({filtered.length})
      </label>
      <span class="text-xs text-c-faint font-mono">{filtered.length} threat{filtered.length !== 1 ? 's' : ''}</span>
    </div>
    <div class="space-y-4">
      {#each filtered as threat (threat.id)}
        <ThreatCard
          {threat}
          readonly={false}
          selectable={true}
          selected={selectedIds.has(threat.id)}
          modelId={params.id}
          commentCount={commentCounts[threat.id] || 0}
          onapprove={handleApprove}
          onreject={handleReject}
          ontoggleSelect={handleToggleSelect}
          ondreadUpdated={updated => threats.update(ts => ts.map(t => t.id === updated.id ? { ...t, ...updated } : t))}
          oncommentChange={detail => { commentCounts[threat.id] = (commentCounts[threat.id] || 0) + detail.delta; commentCounts = commentCounts }} />
      {/each}
    </div>
  {/if}
</div>
