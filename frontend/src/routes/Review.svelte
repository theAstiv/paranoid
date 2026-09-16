<svelte:options runes={true} />

<script>
  import { onMount } from 'svelte'
  import { SvelteSet } from 'svelte/reactivity'
  import { link } from 'svelte-spa-router'
  import { getModelThreats, updateThreat, bulkUpdateThreatStatus, getCommentCounts } from '../lib/api.js'
  import { threats, currentModel, notify } from '../lib/stores.js'
  import ThreatCard from '../components/ThreatCard.svelte'
  import ExportMenu from '../components/ExportMenu.svelte'

  /** @type {{ params?: { id: string } }} */
  let { params = {} } = $props()

  let loading = $state(true)
  let filter = $state('all')
  let sortBy = $state('default')
  let sourceFilter = $state('all')
  let selectedCategories = $state([])
  let dreadMin = $state(0)
  let dreadMax = $state(10)
  let confMin = $state(0)
  let confMax = $state(100)
  let showFilters = $state(false)

  /** @type {SvelteSet<string>} mutations are reactive — no wholesale reassignment */
  const selectedIds = new SvelteSet()
  let bulkBusy = $state(false)
  let commentCounts = $state({})

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

  /** A threat with no DREAD score is never hidden by the range filter. */
  function dreadInRange(t) {
    const s = dreadScoreOf(t)
    return s == null || (s >= dreadMin && s <= dreadMax)
  }

  /** A threat with no confidence value is never hidden by the range filter. */
  function confInRange(t) {
    if (t.confidence == null) return true
    const pct = Math.round(t.confidence * 100)
    return pct >= confMin && pct <= confMax
  }

  const filtered = $derived.by(() => {
    const matched = $threats.filter(t =>
      (filter === 'all' || t.status === filter) &&
      (selectedCategories.length === 0 || selectedCategories.includes(t.stride_category)) &&
      (sourceFilter === 'all' || t.source === sourceFilter) &&
      dreadInRange(t) &&
      confInRange(t)
    )
    return sortThreats(matched, sortBy)
  })

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

  const pendingThreats = $derived($threats.filter(t => t.status === 'pending'))
  const criticalHighPending = $derived(pendingThreats.filter(t => { const s = severityOf(t); return s === 'critical' || s === 'high' }))
  const lowPending = $derived(pendingThreats.filter(t => severityOf(t) === 'low'))

  // Selection is scoped to what is on screen by derivation rather than by a
  // cleanup pass, so a bulk action can never reach a threat the filter hides.
  const visibleSelected = $derived(filtered.filter(t => selectedIds.has(t.id)).map(t => t.id))
  const selectedCount = $derived(visibleSelected.length)
  const allFilteredSelected = $derived(filtered.length > 0 && visibleSelected.length === filtered.length)

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
    if (selectedIds.has(threat.id)) {
      selectedIds.delete(threat.id)
    } else {
      selectedIds.add(threat.id)
    }
  }

  function toggleSelectAll() {
    const selectAll = !allFilteredSelected
    selectedIds.clear()
    if (selectAll) {
      for (const t of filtered) selectedIds.add(t.id)
    }
  }

  async function bulkAction(status) {
    const ids = visibleSelected
    if (ids.length === 0) return
    bulkBusy = true
    const idSet = new Set(ids)
    const originals = $threats.filter(t => idSet.has(t.id)).map(t => ({ id: t.id, status: t.status }))
    threats.update(ts => ts.map(t => idSet.has(t.id) ? { ...t, status } : t))
    try {
      const result = await bulkUpdateThreatStatus(ids, status)
      notify('success', `${result.updated} threats ${status}`)
      selectedIds.clear()
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
          onclick={() => filter = f}
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
      <button type="button" onclick={() => showFilters = !showFilters}
        class="text-xs font-medium text-c-accent hover:text-c-accent/80 transition-colors">
        {showFilters ? 'Hide filters' : 'Filters'}
      </button>
      {#if pendingThreats.length > 0}
        {#if criticalHighPending.length > 0}
          <button type="button" onclick={() => bulkActionFor(criticalHighPending, 'approved', 'Approved Critical/High')} disabled={bulkBusy}
            class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors disabled:opacity-50">
            Approve Critical+High ({criticalHighPending.length})
          </button>
        {/if}
        {#if lowPending.length > 0}
          <button type="button" onclick={() => bulkActionFor(lowPending, 'rejected', 'Rejected Low')} disabled={bulkBusy}
            class="text-xs font-medium text-c-high hover:text-c-high/80 transition-colors disabled:opacity-50">
            Reject Low ({lowPending.length})
          </button>
        {/if}
        <button type="button" onclick={() => bulkActionFor(pendingThreats, 'approved', 'Approved all')} disabled={bulkBusy}
          class="text-xs font-medium text-c-green hover:text-c-green/80 transition-colors disabled:opacity-50">
          Approve all ({pendingThreats.length})
        </button>
        <button type="button" onclick={() => bulkActionFor(pendingThreats, 'rejected', 'Rejected all')} disabled={bulkBusy}
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
              <button type="button" onclick={() => toggleCategory(cat)}
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
              <button type="button" onclick={() => sourceFilter = val}
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
      <button type="button" onclick={() => bulkAction('approved')} disabled={bulkBusy}
        class="btn-primary text-xs px-3 py-1 disabled:opacity-50">
        Approve selected ({selectedCount})
      </button>
      <button type="button" onclick={() => bulkAction('rejected')} disabled={bulkBusy}
        class="btn-ghost text-xs px-3 py-1 disabled:opacity-50">
        Reject selected ({selectedCount})
      </button>
      <button type="button" onclick={() => selectedIds.clear()}
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
        <input type="checkbox" checked={allFilteredSelected} onchange={toggleSelectAll}
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
          oncommentChange={detail => { commentCounts[threat.id] = (commentCounts[threat.id] || 0) + detail.delta }} />
      {/each}
    </div>
  {/if}
</div>
