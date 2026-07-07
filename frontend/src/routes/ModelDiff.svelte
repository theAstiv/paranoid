<script>
  import { onMount } from 'svelte'
  import { link } from 'svelte-spa-router'
  import { getModel, listModels, compareModels } from '../lib/api.js'
  import { notify } from '../lib/stores.js'

  /** @type {{ id: string }} */
  export let params = {}

  let head = null
  let allModels = []
  let baseId = ''
  let diffResult = null
  let loading = true
  let diffLoading = false
  let filter = 'all'

  const FILTERS = [
    { key: 'all',       label: 'All' },
    { key: 'added',     label: 'Added' },
    { key: 'removed',   label: 'Removed' },
    { key: 'changed',   label: 'Changed' },
    { key: 'unchanged', label: 'Unchanged' },
  ]

  $: filtered = !diffResult ? [] : (
    filter === 'all'
      ? diffResult.threats
      : diffResult.threats.filter(e => e.status === filter)
  )

  // Only completed models carry a full threat set — filter to avoid confusing
  // partial diffs against in-progress or failed runs.
  // TODO: paginate when listModels supports cursor-based pagination (limit=50 silently truncates).
  $: availableBases = allModels.filter(m => m.id !== params.id && m.status === 'completed')

  onMount(async () => {
    try {
      [head, allModels] = await Promise.all([
        getModel(params.id),
        listModels({ limit: 50 }),
      ])
    } catch (err) {
      notify('error', `Failed to load model: ${err.message}`)
    } finally {
      loading = false
    }
  })

  async function runDiff() {
    if (!baseId) return
    diffLoading = true
    diffResult = null
    try {
      diffResult = await compareModels(params.id, baseId)
    } catch (err) {
      notify('error', `Diff failed: ${err.message}`)
    } finally {
      diffLoading = false
    }
  }

  function threatOf(entry) {
    return entry.head ?? entry.base
  }

  function dreadScore(t) {
    if (!t) return null
    if (t.dread_score != null) return Number(t.dread_score).toFixed(1)
    return null
  }

  function severityClass(score) {
    if (score == null) return 'text-c-muted'
    const n = Number(score)
    if (n >= 8) return 'text-c-critical'
    if (n >= 6) return 'text-c-high'
    if (n >= 4) return 'text-c-medium'
    return 'text-c-low'
  }

  const STATUS_CONFIG = {
    added:     { chip: 'chip-green',  symbol: '+', label: 'Added' },
    removed:   { chip: 'chip-red',    symbol: '−', label: 'Removed' },
    changed:   { chip: 'chip-amber',  symbol: '~', label: 'Changed' },
    unchanged: { chip: 'chip-gray',   symbol: '=', label: 'Unchanged' },
  }
</script>

<div class="max-w-[1120px] mx-auto space-y-5">
  <!-- Breadcrumb -->
  <div class="flex items-center gap-2 text-sm text-c-muted">
    <a href={`#/models/${params.id}`} use:link class="hover:text-c-text transition-colors">
      {head?.title ?? params.id}
    </a>
    <span class="text-c-faint">›</span>
    <span class="text-c-text2">Re-run Diff</span>
  </div>

  <!-- Header -->
  <div class="bg-c-panel border border-c-border rounded-panel p-5">
    <h1 class="text-lg font-semibold text-c-text mb-1">Re-run Diff</h1>
    <p class="text-sm text-c-muted mb-5">
      Compare this model's threats against a prior run to see what was added, removed, or changed.
    </p>

    <!-- Base model picker -->
    <div class="flex items-end gap-3 flex-wrap">
      <div class="flex-1 min-w-[220px]">
        <label class="block text-xs text-c-muted mb-1" for="base-select">Compare against</label>
        {#if loading}
          <div class="h-9 bg-c-input border border-c-border rounded-panel animate-pulse"></div>
        {:else}
          <select
            id="base-select"
            bind:value={baseId}
            class="w-full h-9 bg-c-input border border-c-border rounded-panel px-3 text-sm text-c-text focus:outline-none focus:border-c-accent"
          >
            <option value="">— select a base model —</option>
            {#each availableBases as m}
              <option value={m.id}>{m.title} ({m.framework}, {m.status})</option>
            {/each}
          </select>
        {/if}
      </div>
      <button
        class="btn-primary h-9 px-5 text-sm"
        disabled={!baseId || diffLoading}
        on:click={runDiff}
      >
        {#if diffLoading}
          <span class="flex items-center gap-2">
            <span class="w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin-slow"></span>
            Comparing…
          </span>
        {:else}
          Compare
        {/if}
      </button>
    </div>
  </div>

  <!-- Diff results -->
  {#if diffResult}
    {@const s = diffResult.summary}

    <!-- Summary stats -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <div class="bg-c-panel border border-c-border rounded-panel p-4 text-center">
        <div class="text-2xl font-semibold font-mono text-c-green">{s.added}</div>
        <div class="text-xs text-c-muted mt-1">Added</div>
      </div>
      <div class="bg-c-panel border border-c-border rounded-panel p-4 text-center">
        <div class="text-2xl font-semibold font-mono text-c-critical">{s.removed}</div>
        <div class="text-xs text-c-muted mt-1">Removed</div>
      </div>
      <div class="bg-c-panel border border-c-border rounded-panel p-4 text-center">
        <div class="text-2xl font-semibold font-mono text-c-high">{s.changed}</div>
        <div class="text-xs text-c-muted mt-1">Changed</div>
      </div>
      <div class="bg-c-panel border border-c-border rounded-panel p-4 text-center">
        <div class="text-2xl font-semibold font-mono text-c-muted">{s.unchanged}</div>
        <div class="text-xs text-c-muted mt-1">Unchanged</div>
      </div>
    </div>

    <!-- Filter tabs -->
    <div class="flex gap-1.5 flex-wrap">
      {#each FILTERS as f}
        {@const count = f.key === 'all' ? diffResult.threats.length : s[f.key] ?? 0}
        <button
          class="px-3 py-1.5 rounded-pill text-xs font-medium transition-colors
            {filter === f.key
              ? 'bg-c-accent text-c-bg'
              : 'bg-c-panel border border-c-border text-c-muted hover:text-c-text'}"
          on:click={() => filter = f.key}
        >
          {f.label}
          <span class="ml-1 font-mono opacity-70">{count}</span>
        </button>
      {/each}
    </div>

    <!-- Threat list -->
    {#if filtered.length === 0}
      <div class="text-center py-12 text-c-muted text-sm">
        No threats match this filter.
      </div>
    {:else}
      <div class="space-y-2">
        {#each filtered as entry}
          {@const t = threatOf(entry)}
          {@const cfg = STATUS_CONFIG[entry.status]}
          {@const score = dreadScore(entry.status === 'removed' ? entry.base : entry.head)}

          <div class="bg-c-panel border border-c-border rounded-panel p-4 flex gap-3">
            <!-- Status symbol -->
            <div class="flex-none w-6 h-6 mt-0.5 flex items-center justify-center rounded font-mono text-sm font-semibold
              {entry.status === 'added'     ? 'bg-c-green/10 text-c-green' :
               entry.status === 'removed'   ? 'bg-c-critical/10 text-c-critical' :
               entry.status === 'changed'   ? 'bg-c-high/10 text-c-high' :
                                              'bg-c-faint/10 text-c-faint'}">
              {cfg.symbol}
            </div>

            <div class="flex-1 min-w-0">
              <div class="flex items-start justify-between gap-3 flex-wrap">
                <div class="min-w-0">
                  <span class="font-medium text-c-text text-sm">{t?.name ?? '—'}</span>
                  <span class="ml-2 text-xs text-c-muted">→ {t?.target ?? ''}</span>
                </div>
                <div class="flex items-center gap-2 flex-none">
                  {#if t?.stride_category}
                    <span class="chip-gray text-xs px-2 py-0.5 rounded-chip">{t.stride_category}</span>
                  {/if}
                  {#if score != null}
                    <span class="font-mono text-xs {severityClass(score)}">DREAD {score}</span>
                  {/if}
                  <span class="{cfg.chip} text-xs px-2 py-0.5 rounded-chip">{cfg.label}</span>
                </div>
              </div>

              <!-- Description -->
              <p class="text-xs text-c-text2 mt-2 leading-relaxed line-clamp-2">
                {t?.description ?? ''}
              </p>

              <!-- Changed: show DREAD delta and base description -->
              {#if entry.status === 'changed' && entry.dread_delta != null && Math.abs(entry.dread_delta) >= 0.1}
                <div class="mt-2 flex items-center gap-2 text-xs">
                  <span class="text-c-muted">DREAD:</span>
                  <span class="font-mono {entry.dread_delta > 0 ? 'text-c-critical' : 'text-c-green'}">
                    {entry.dread_delta > 0 ? '+' : ''}{entry.dread_delta.toFixed(1)}
                  </span>
                  {#if entry.base?.description && entry.head?.description && entry.base.description !== entry.head.description}
                    <span class="text-c-faint">· description changed</span>
                  {/if}
                </div>
              {/if}

              <!-- Changed: base description (collapsed) -->
              {#if entry.status === 'changed' && entry.base}
                <details class="mt-2">
                  <summary class="text-xs text-c-muted cursor-pointer hover:text-c-text2 select-none">
                    Prior description
                  </summary>
                  <p class="text-xs text-c-muted mt-1 pl-3 border-l border-c-border leading-relaxed">
                    {entry.base.description}
                  </p>
                </details>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>
