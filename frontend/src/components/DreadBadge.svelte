<script>
  import { dreadChip, dreadLabel, dreadColor } from '../lib/utils.js'

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

  function normalizeThreat(t) {
    if (!t) return null
    if (t.dread?.damage != null) {
      const d = t.dread
      return { damage: d.damage, reproducibility: d.reproducibility, exploitability: d.exploitability, affected_users: d.affected_users, discoverability: d.discoverability }
    }
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
      class="inline-flex items-center gap-1 font-mono text-[11px] px-2 py-0.5 rounded-chip border transition-colors {dreadChip(score)}">
      DREAD {score}
    </button>

    {#if expanded && normalized}
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
      <div class="fixed inset-0 z-10" on:click={() => expanded = false}></div>
      <div class="absolute bottom-full left-0 mb-2 z-20 bg-c-panel border border-c-border rounded-panel shadow-xl p-3 w-48 animate-pop-in">
        <p class="font-mono text-[10px] font-semibold text-c-muted mb-2 uppercase tracking-wide">DREAD breakdown</p>
        <dl class="space-y-1.5">
          {#each DIMS as [, label, key]}
            <div class="flex items-center justify-between text-xs">
              <dt class="text-c-muted">{label}</dt>
              <dd class="font-mono font-semibold {dreadColor(normalized[key] ?? 0)}">
                {normalized[key] ?? '—'}
              </dd>
            </div>
          {/each}
        </dl>
      </div>
    {/if}
  </div>
{/if}
