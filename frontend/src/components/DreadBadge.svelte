<script>
  /**
   * Pass the full threat object. DreadBadge normalizes the DREAD data internally.
   *
   * Two shapes exist depending on the source:
   *   SSE events  → threat.dread = { damage, reproducibility, exploitability, affected_users, discoverability }
   *   DB/API GET  → flat columns: threat.dread_damage, threat.dread_reproducibility, …
   *
   * @type {object|null}
   */
  export let threat = null

  let expanded = false

  $: normalized = normalizeThreat(threat)
  $: score = normalized ? avg(normalized) : null
  $: color = score == null ? '' : score <= 3 ? 'bg-green-100 text-green-800' : score <= 6 ? 'bg-yellow-100 text-yellow-800' : 'bg-red-100 text-red-800'

  function normalizeThreat(t) {
    if (!t) return null
    // SSE shape: nested dread object on the threat
    if (t.dread?.damage != null) {
      const d = t.dread
      return { damage: d.damage, reproducibility: d.reproducibility, exploitability: d.exploitability, affected_users: d.affected_users, discoverability: d.discoverability }
    }
    // DB/API shape: flat dread_* columns directly on the threat record
    if (t.dread_damage != null) {
      return { damage: t.dread_damage, reproducibility: t.dread_reproducibility, exploitability: t.dread_exploitability, affected_users: t.dread_affected_users, discoverability: t.dread_discoverability }
    }
    return null
  }

  function avg(d) {
    const vals = [d.damage, d.reproducibility, d.exploitability, d.affected_users, d.discoverability].filter(v => v != null)
    if (!vals.length) return null
    return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10
  }

  const DIMS = [
    ['D', 'Damage', 'damage'],
    ['R', 'Reproducibility', 'reproducibility'],
    ['E', 'Exploitability', 'exploitability'],
    ['A', 'Affected Users', 'affected_users'],
    ['D', 'Discoverability', 'discoverability'],
  ]
</script>

{#if score != null}
  <div class="relative inline-block">
    <button
      type="button"
      on:click={() => expanded = !expanded}
      class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold {color}">
      DREAD: {score}
    </button>

    {#if expanded && normalized}
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
      <div class="fixed inset-0 z-10" on:click={() => expanded = false}></div>
      <div class="absolute bottom-full left-0 mb-1 z-20 bg-white border border-slate-200 rounded-lg shadow-lg p-3 w-48">
        <p class="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wide">DREAD breakdown</p>
        <dl class="space-y-1">
          {#each DIMS as [abbr, label, key]}
            <div class="flex items-center justify-between text-xs">
              <dt class="text-slate-600">{label}</dt>
              <dd class="font-mono font-medium {normalized[key] >= 7 ? 'text-red-600' : normalized[key] >= 4 ? 'text-yellow-600' : 'text-green-600'}">
                {normalized[key] ?? '—'}
              </dd>
            </div>
          {/each}
        </dl>
      </div>
    {/if}
  </div>
{/if}
